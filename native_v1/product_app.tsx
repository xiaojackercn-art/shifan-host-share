import { useCallback, useEffect, useMemo, useState } from 'react'
import { invoke } from '@tauri-apps/api/core'
import {
  hideMainWindow,
  loadAppState,
  minimizeMainWindow,
  saveLayout,
  startRuntime,
  startWindowDrag,
  toggleMaximizeMainWindow,
} from './desktopApi'
import { APP_VERSION } from './constants'
import type { AppStateSnapshot, RuntimeStatus } from './runtime'
import type { Device, LayoutState, MachineRole, Screen } from './types'

const PRODUCT = '视饭AI:主机共享'

type Position = 'left' | 'right' | 'top' | 'bottom'

interface ConnectionKeyPayload {
  version: 1
  endpointId: string
  name: string
  platform: string
  clusterId: string
  pairSecret: string
  screens: Screen[]
}

const KEY_PREFIX = 'SFAI1-'

function encodeBase64Url(bytes: Uint8Array) {
  let binary = ''
  for (const byte of bytes) binary += String.fromCharCode(byte)
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '')
}

function decodeBase64Url(value: string) {
  const padded = value.replace(/-/g, '+').replace(/_/g, '/') + '==='.slice((value.length + 3) % 4)
  const binary = atob(padded)
  return Uint8Array.from(binary, (char) => char.charCodeAt(0))
}

function remoteDevices(layout?: LayoutState) {
  return layout?.devices.filter((device) => device.role !== 'local') ?? []
}

function localDevice(layout?: LayoutState) {
  return layout?.devices.find((device) => device.role === 'local') ?? layout?.devices[0]
}

function makeConnectionKey(layout: LayoutState, runtime: RuntimeStatus) {
  const local = localDevice(layout)
  const endpointId = runtime.discovery.localPeer.transportPublicKey.trim()
  if (!local || !endpointId || !layout.clusterId.trim() || !layout.pairSecret.trim()) return ''
  const payload: ConnectionKeyPayload = {
    version: 1,
    endpointId,
    name: local.name,
    platform: local.platform,
    clusterId: layout.clusterId,
    pairSecret: layout.pairSecret,
    screens: local.screens,
  }
  return KEY_PREFIX + encodeBase64Url(new TextEncoder().encode(JSON.stringify(payload)))
}

function parseConnectionKey(key: string): ConnectionKeyPayload {
  const normalized = key.trim()
  if (!normalized.startsWith(KEY_PREFIX)) throw new Error('连接密钥格式不正确。')
  const raw = normalized.slice(KEY_PREFIX.length)
  if (!raw || raw.length > 24000) throw new Error('连接密钥格式不正确。')
  let parsed: ConnectionKeyPayload
  try {
    parsed = JSON.parse(new TextDecoder().decode(decodeBase64Url(raw))) as ConnectionKeyPayload
  } catch {
    throw new Error('连接密钥无法解析，请重新复制完整密钥。')
  }
  if (
    parsed.version !== 1 ||
    !parsed.endpointId?.trim() ||
    !parsed.clusterId?.trim() ||
    !parsed.pairSecret?.trim() ||
    !Array.isArray(parsed.screens) ||
    parsed.screens.length === 0
  ) {
    throw new Error('连接密钥内容不完整，请在被控电脑重新复制。')
  }
  return parsed
}

function deviceFromConnectionKey(payload: ConnectionKeyPayload, layout: LayoutState, local: Device): Device {
  const base = local.screens.find((screen) => screen.isPrimary) ?? local.screens[0]
  const sourceScreens = payload.screens.slice(0, 16)
  const minX = Math.min(...sourceScreens.map((screen) => screen.x))
  const minY = Math.min(...sourceScreens.map((screen) => screen.y))
  const originX = (base?.x ?? 0) + (base?.width ?? 1920)
  const originY = base?.y ?? 0
  const primaryIndex = Math.max(0, sourceScreens.findIndex((screen) => screen.isPrimary))
  const endpointId = payload.endpointId.trim()
  const screens = sourceScreens.map((screen, index) => ({
    ...screen,
    id: `${endpointId}-${screen.id || `screen-${index + 1}`}`,
    deviceId: endpointId,
    x: originX + (screen.x - minX),
    y: originY + (screen.y - minY),
    width: Math.max(1, Number(screen.width) || 1920),
    height: Math.max(1, Number(screen.height) || 1080),
    scale: Math.max(0.25, Number(screen.scale) || 1),
    isPrimary: index === primaryIndex,
  }))
  return {
    id: endpointId,
    name: payload.name?.trim() || '远程电脑',
    platform: payload.platform === 'macos' || payload.platform === 'windows' ? payload.platform : 'unknown',
    host: `wan://${endpointId}/${payload.clusterId}/${payload.pairSecret}`,
    transportPort: layout.transportPort,
    quicPort: layout.quicPort,
    transportPublicKey: endpointId,
    protocolVersion: 2,
    color: '#0f766e',
    online: true,
    inputReady: true,
    upgrading: false,
    role: 'client',
    source: 'wan-key',
    screens,
  }
}

function normalizeScreensForPosition(local: Device, remote: Device, position: Position): Screen[] {
  const base = local.screens.find((screen) => screen.isPrimary) ?? local.screens[0]
  if (!base || remote.screens.length === 0) return remote.screens

  const minX = Math.min(...remote.screens.map((screen) => screen.x))
  const minY = Math.min(...remote.screens.map((screen) => screen.y))
  const maxX = Math.max(...remote.screens.map((screen) => screen.x + screen.width))
  const maxY = Math.max(...remote.screens.map((screen) => screen.y + screen.height))
  const width = maxX - minX
  const height = maxY - minY

  let originX = base.x + base.width
  let originY = base.y
  if (position === 'left') originX = base.x - width
  if (position === 'top') {
    originX = base.x
    originY = base.y - height
  }
  if (position === 'bottom') {
    originX = base.x
    originY = base.y + base.height
  }

  return remote.screens.map((screen) => ({
    ...screen,
    x: originX + (screen.x - minX),
    y: originY + (screen.y - minY),
  }))
}

export default function App() {
  const [snapshot, setSnapshot] = useState<AppStateSnapshot | null>(null)
  const [runtime, setRuntime] = useState<RuntimeStatus | null>(null)
  const [connectionKey, setConnectionKey] = useState('')
  const [keyInput, setKeyInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [copied, setCopied] = useState(false)

  const layout = snapshot?.layout
  const role = layout?.machineRole ?? 'unset'
  const local = useMemo(() => localDevice(layout), [layout])
  const remotes = useMemo(() => remoteDevices(layout), [layout])

  const refreshKey = useCallback(async () => {
    if (role !== 'client' || !layout || !runtime) return
    const key = makeConnectionKey(layout, runtime)
    setConnectionKey(key)
    setMessage(key ? '' : '正在准备公网连接，请稍候…')
  }, [role, layout, runtime])

  useEffect(() => {
    let alive = true
    void (async () => {
      try {
        const state = await loadAppState()
        if (!alive) return
        setSnapshot(state)
        setRuntime(state.runtime)
        if (state.layout.machineRole !== 'unset') {
          const next = await startRuntime()
          if (alive) setRuntime(next)
        }
      } catch (error) {
        if (alive) setMessage(String(error))
      }
    })()
    return () => {
      alive = false
    }
  }, [])

  useEffect(() => {
    void refreshKey()
  }, [refreshKey])

  async function chooseRole(nextRole: MachineRole) {
    if (!layout) return
    setBusy(true)
    setMessage('')
    try {
      const nextLayout: LayoutState = {
        ...layout,
        devices: layout.devices.filter((device) => device.role === 'local'),
        machineRole: nextRole,
        inputMode: nextRole === 'client' ? 'receive' : 'control',
        clipboardSync: false,
        fileTransferEnabled: false,
      }
      const state = await saveLayout(nextLayout)
      setSnapshot(state)
      const nextRuntime = await startRuntime()
      setRuntime(nextRuntime)
      setConnectionKey('')
    } catch (error) {
      setMessage(String(error))
    } finally {
      setBusy(false)
    }
  }

  async function copyKey() {
    if (!connectionKey) return
    try {
      await navigator.clipboard.writeText(connectionKey)
    } catch {
      await invoke('write_clipboard_text', { text: connectionKey })
    }
    setCopied(true)
    window.setTimeout(() => setCopied(false), 1600)
  }

  async function connectByKey() {
    const key = keyInput.trim()
    if (!key) {
      setMessage('请先粘贴另一台电脑显示的连接密钥。')
      return
    }
    if (!layout || !local) return
    setBusy(true)
    setMessage('正在通过公网建立加密连接…')
    try {
      const payload = parseConnectionKey(key)
      await invoke('probe_wan_peer', { endpointId: payload.endpointId })
      const remote = deviceFromConnectionKey(payload, layout, local)
      const devices = [
        ...layout.devices.filter((device) => device.role === 'local' || device.id !== remote.id),
        remote,
      ]
      const state = await saveLayout({
        ...layout,
        devices,
        inputMode: 'control',
        clipboardSync: false,
        fileTransferEnabled: false,
      })
      setSnapshot(state)
      setRuntime(state.runtime)
      setKeyInput('')
      setMessage(`已连接 ${remote.name}。选择屏幕方向后，把鼠标推过对应边缘即可。`)
    } catch (error) {
      setMessage(`连接失败：${String(error)}`)
    } finally {
      setBusy(false)
    }
  }

  async function placeRemote(deviceId: string, position: Position) {
    if (!layout || !local) return
    const target = layout.devices.find((device) => device.id === deviceId)
    if (!target) return
    setBusy(true)
    try {
      const devices = layout.devices.map((device) =>
        device.id === deviceId
          ? { ...device, screens: normalizeScreensForPosition(local, target, position) }
          : device,
      )
      const state = await saveLayout({ ...layout, devices })
      setSnapshot(state)
      setRuntime(state.runtime)
      setMessage('屏幕位置已更新。')
    } catch (error) {
      setMessage(String(error))
    } finally {
      setBusy(false)
    }
  }

  async function removeRemote(deviceId: string) {
    if (!layout) return
    setBusy(true)
    try {
      const devices = layout.devices.filter((device) => device.id !== deviceId)
      const state = await saveLayout({ ...layout, devices })
      setSnapshot(state)
      setRuntime(state.runtime)
      setMessage('已删除这台电脑的连接信息。')
    } catch (error) {
      setMessage(String(error))
    } finally {
      setBusy(false)
    }
  }

  const online = Boolean(runtime?.started && runtime.discovery.localPeer.transportPublicKey)

  if (!snapshot) {
    return (
      <div className="app-shell loading-shell">
        <img src="/app-icon.png" className="loading-logo" alt={PRODUCT} />
        <h1>正在启动 {PRODUCT}</h1>
        <p>{message || '正在初始化键鼠服务和公网连接…'}</p>
      </div>
    )
  }

  return (
    <div className="app-shell">
      <header className="titlebar" onMouseDown={() => void startWindowDrag()}>
        <div className="title-brand">
          <img src="/app-icon.png" alt={PRODUCT} />
          <div>
            <strong>{PRODUCT}</strong>
            <span>一套键鼠 · 跨网络控制 Windows / macOS</span>
          </div>
        </div>
        <div className="window-buttons" onMouseDown={(event) => event.stopPropagation()}>
          <button onClick={() => void minimizeMainWindow()} aria-label="最小化">—</button>
          <button onClick={() => void toggleMaximizeMainWindow()} aria-label="最大化">□</button>
          <button className="close" onClick={() => void hideMainWindow()} aria-label="关闭">×</button>
        </div>
      </header>

      <main>
        <section className="hero">
          <div>
            <span className={`status-pill ${online ? 'online' : ''}`}>
              <i />{online ? '公网服务已就绪' : '正在连接公网服务'}
            </span>
            <h1>不同网络，也只用一套键盘鼠标</h1>
            <p>不要求同一个 Wi‑Fi，不需要填写 IP、端口或做路由器端口映射。被控电脑复制一个连接密钥，主控电脑粘贴后即可建立连接。</p>
          </div>
          <img src="/app-icon.png" className="hero-logo" alt="视饭AI主机共享 Logo" />
        </section>

        {role === 'unset' ? (
          <section className="role-section">
            <div className="section-head">
              <span>第一次使用</span>
              <h2>这台电脑连接着你正在使用的键盘鼠标吗？</h2>
            </div>
            <div className="role-grid">
              <button className="role-card primary" disabled={busy} onClick={() => void chooseRole('server')}>
                <b>主控电脑</b>
                <strong>是，键盘鼠标在这台</strong>
                <p>在这里粘贴另一台电脑的连接密钥，然后用本机键鼠跨屏控制。</p>
                <span>选择主控电脑 →</span>
              </button>
              <button className="role-card" disabled={busy} onClick={() => void chooseRole('client')}>
                <b>被控电脑</b>
                <strong>不是，这台等着被控制</strong>
                <p>这台会生成唯一连接密钥，把它复制给主控电脑即可。</p>
                <span>选择被控电脑 →</span>
              </button>
            </div>
          </section>
        ) : role === 'client' ? (
          <section className="workspace client-workspace">
            <div className="workspace-title">
              <div>
                <span>被控电脑</span>
                <h2>复制这一个连接密钥</h2>
                <p>把下面整段密钥发到主控电脑。两台电脑可以处在完全不同的局域网。</p>
              </div>
              <button className="ghost" disabled={busy} onClick={() => void chooseRole('server')}>改成主控电脑</button>
            </div>

            <div className="key-panel">
              <div className="key-status">
                <i className={online ? 'ready' : ''} />
                <span>{online ? '公网连接服务已启动 / 可被连接' : '正在准备公网连接'}</span>
              </div>
              <textarea value={connectionKey} readOnly spellCheck={false} placeholder="正在生成连接密钥…" />
              <div className="key-actions">
                <button className="primary-button" disabled={!connectionKey} onClick={() => void copyKey()}>
                  {copied ? '已复制' : '复制连接密钥'}
                </button>
                <button className="secondary-button" onClick={() => void refreshKey()}>刷新显示</button>
              </div>
            </div>

            <div className="steps">
              <div><span>1</span><p><strong>保持本软件运行</strong>可以最小化到后台，不需要一直打开窗口。</p></div>
              <div><span>2</span><p><strong>复制上面的密钥</strong>通过微信、飞书等方式发给主控电脑。</p></div>
              <div><span>3</span><p><strong>主控电脑粘贴并连接</strong>以后会记住，不需要每次重新输入。</p></div>
            </div>
          </section>
        ) : (
          <section className="workspace server-workspace">
            <div className="workspace-title">
              <div>
                <span>主控电脑</span>
                <h2>粘贴连接密钥</h2>
                <p>连接密钥来自另一台“被控电脑”。无需知道对方公网 IP。</p>
              </div>
              <button className="ghost" disabled={busy} onClick={() => void chooseRole('client')}>改成被控电脑</button>
            </div>

            <div className="connect-panel">
              <textarea
                value={keyInput}
                onChange={(event) => setKeyInput(event.target.value)}
                spellCheck={false}
                placeholder="在这里粘贴 SFAI1- 开头的连接密钥"
              />
              <button className="primary-button connect-button" disabled={busy || !keyInput.trim()} onClick={() => void connectByKey()}>
                {busy ? '正在连接…' : '连接这台电脑'}
              </button>
            </div>

            <div className="device-area">
              <div className="device-area-head">
                <h3>已连接电脑</h3>
                <span>{remotes.length} 台</span>
              </div>
              {remotes.length === 0 ? (
                <div className="empty-device">
                  <div className="empty-icon">＋</div>
                  <strong>还没有添加被控电脑</strong>
                  <p>在另一台电脑选择“被控电脑”，复制密钥后粘贴到上方。</p>
                </div>
              ) : (
                <div className="device-list">
                  {remotes.map((device) => (
                    <article className="device-card" key={device.id}>
                      <div className="device-main">
                        <div className="computer-icon">▣</div>
                        <div>
                          <strong>{device.name}</strong>
                          <span>{device.platform === 'macos' ? 'macOS' : device.platform === 'windows' ? 'Windows' : device.platform} · {device.screens.length} 屏</span>
                        </div>
                        <em>{device.inputReady ? '已配置' : '等待连接'}</em>
                      </div>
                      <div className="position-row">
                        <span>这台电脑在主屏的哪一边？</span>
                        <div>
                          <button onClick={() => void placeRemote(device.id, 'left')}>← 左</button>
                          <button onClick={() => void placeRemote(device.id, 'right')}>右 →</button>
                          <button onClick={() => void placeRemote(device.id, 'top')}>↑ 上</button>
                          <button onClick={() => void placeRemote(device.id, 'bottom')}>↓ 下</button>
                        </div>
                      </div>
                      <button className="remove-link" onClick={() => void removeRemote(device.id)}>删除连接</button>
                    </article>
                  ))}
                </div>
              )}
            </div>
          </section>
        )}

        {message ? <div className={`message ${message.includes('失败') || message.includes('invalid') ? 'error' : ''}`}>{message}</div> : null}

        <footer>
          <span>{local?.name ?? '本机'} · v{APP_VERSION}</span>
          <span>连接密钥请只发给你信任的人</span>
        </footer>
      </main>
    </div>
  )
}
