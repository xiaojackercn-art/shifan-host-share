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
const KEY_PREFIX = 'SFAI1-'

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

function BrandMark({ compact = false }: { compact?: boolean }) {
  return (
    <span className={`brand-mark ${compact ? 'compact' : ''}`} aria-hidden="true">
      <svg viewBox="0 0 48 48" role="img">
        <rect x="4" y="9" width="24" height="18" rx="4" />
        <path d="M12 33h9M16.5 27v6" />
        <rect x="23" y="19" width="21" height="16" rx="4" className="brand-mark-secondary" />
        <path d="M29 39h9M33.5 35v4" className="brand-mark-secondary" />
        <path d="M17 18h11M25 14l4 4-4 4" className="brand-mark-link" />
      </svg>
    </span>
  )
}

function ComputerIcon() {
  return (
    <span className="computer-icon" aria-hidden="true">
      <svg viewBox="0 0 32 32">
        <rect x="4" y="5" width="24" height="17" rx="3" />
        <path d="M12 27h8M16 22v5" />
      </svg>
    </span>
  )
}

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

function platformLabel(platform: string) {
  if (platform === 'windows') return 'Windows'
  if (platform === 'macos') return 'macOS'
  return platform || '未知系统'
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
    color: '#2563eb',
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

function DirectionButtons({ disabled, onSelect }: { disabled: boolean; onSelect: (position: Position) => void }) {
  return (
    <div className="direction-buttons">
      <button disabled={disabled} onClick={() => onSelect('left')}><span>←</span> 左侧</button>
      <button disabled={disabled} onClick={() => onSelect('right')}>右侧 <span>→</span></button>
      <button disabled={disabled} onClick={() => onSelect('top')}><span>↑</span> 上方</button>
      <button disabled={disabled} onClick={() => onSelect('bottom')}><span>↓</span> 下方</button>
    </div>
  )
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
  const online = Boolean(runtime?.started && runtime.discovery.localPeer.transportPublicKey)

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
    setMessage('正在建立加密连接…')
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
      setMessage(`已连接 ${remote.name}。设置屏幕位置后，把鼠标推过对应边缘即可切换。`)
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
      setMessage('屏幕位置已保存。')
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

  if (!snapshot) {
    return (
      <div className="app-shell loading-shell">
        <BrandMark />
        <div className="loading-copy">
          <h1>{PRODUCT}</h1>
          <p>{message || '正在初始化输入服务与安全连接…'}</p>
        </div>
      </div>
    )
  }

  return (
    <div className="app-shell">
      <header className="titlebar" onMouseDown={() => void startWindowDrag()}>
        <div className="title-brand">
          <BrandMark compact />
          <div>
            <strong>{PRODUCT}</strong>
            <span>跨设备键鼠控制</span>
          </div>
        </div>
        <div className="title-status">
          <span className={`status-dot ${online ? 'online' : ''}`} />
          {online ? '连接服务正常' : '正在启动连接服务'}
        </div>
        <div className="window-buttons" onMouseDown={(event) => event.stopPropagation()}>
          <button onClick={() => void minimizeMainWindow()} aria-label="最小化">—</button>
          <button onClick={() => void toggleMaximizeMainWindow()} aria-label="最大化">□</button>
          <button className="close" onClick={() => void hideMainWindow()} aria-label="关闭">×</button>
        </div>
      </header>

      <main className="page">
        <section className="overview-card">
          <div className="overview-copy">
            <span className="eyebrow">SHIFAN HOST SHARE</span>
            <h1>一套键鼠，自然切换多台电脑</h1>
            <p>支持 Windows 与 macOS 跨网络连接。无需公网 IP、端口映射或同一 Wi‑Fi，连接完成后把鼠标推过屏幕边缘即可切换，键盘会跟随当前电脑。</p>
            <div className="feature-row">
              <span>公网直连 / 中继回退</span>
              <span>低延迟鼠标通道</span>
              <span>键盘跟随</span>
              <span>加密连接密钥</span>
            </div>
          </div>
          <div className="monitor-scene" aria-hidden="true">
            <div className="monitor monitor-main"><span>主控电脑</span><i /></div>
            <div className="monitor-bridge"><span>→</span></div>
            <div className="monitor monitor-remote"><span>被控电脑</span><i /></div>
          </div>
        </section>

        {role === 'unset' ? (
          <section className="panel role-panel">
            <div className="panel-heading">
              <div>
                <span className="section-kicker">首次设置</span>
                <h2>选择这台电脑的角色</h2>
                <p>两台电脑各选一次即可，后续可以随时切换。</p>
              </div>
            </div>
            <div className="role-grid">
              <button className="role-card selected" disabled={busy} onClick={() => void chooseRole('server')}>
                <div className="role-card-top"><span className="role-number">01</span><span className="role-chip">主控</span></div>
                <ComputerIcon />
                <strong>键盘鼠标连接在这台电脑</strong>
                <p>用这台电脑的键盘鼠标控制其他电脑。</p>
                <span className="role-action">设为主控电脑 <b>→</b></span>
              </button>
              <button className="role-card" disabled={busy} onClick={() => void chooseRole('client')}>
                <div className="role-card-top"><span className="role-number">02</span><span className="role-chip muted">被控</span></div>
                <ComputerIcon />
                <strong>这台电脑等待被另一台控制</strong>
                <p>生成连接密钥，交给主控电脑即可。</p>
                <span className="role-action">设为被控电脑 <b>→</b></span>
              </button>
            </div>
          </section>
        ) : role === 'client' ? (
          <section className="workspace-grid client-grid">
            <section className="panel key-card">
              <div className="panel-heading horizontal">
                <div>
                  <span className="section-kicker">被控电脑</span>
                  <h2>连接密钥</h2>
                  <p>复制整段密钥到主控电脑。密钥包含本机连接身份，请只发给可信设备。</p>
                </div>
                <button className="text-button" disabled={busy} onClick={() => void chooseRole('server')}>切换为主控</button>
              </div>

              <div className={`service-banner ${online ? 'ready' : ''}`}>
                <span className="status-dot online" />
                <div>
                  <strong>{online ? '本机已准备好接收控制' : '正在建立公网连接能力'}</strong>
                  <p>{online ? '可以复制下方密钥并在主控电脑连接。' : '通常只需要几秒钟，请保持软件运行。'}</p>
                </div>
              </div>

              <label className="field-label" htmlFor="connection-key">本机连接密钥</label>
              <textarea id="connection-key" className="key-textarea" value={connectionKey} readOnly spellCheck={false} placeholder="正在生成连接密钥…" />
              <div className="button-row">
                <button className="button primary" disabled={!connectionKey} onClick={() => void copyKey()}>{copied ? '已复制到剪贴板' : '复制连接密钥'}</button>
                <button className="button secondary" onClick={() => void refreshKey()}>刷新密钥显示</button>
              </div>
            </section>

            <aside className="panel guide-card">
              <span className="section-kicker">连接方法</span>
              <h3>主控电脑只需要三步</h3>
              <ol className="guide-list">
                <li><span>1</span><div><strong>复制密钥</strong><p>复制左侧完整的 SFAI1- 连接密钥。</p></div></li>
                <li><span>2</span><div><strong>在主控电脑粘贴</strong><p>打开“视饭AI:主机共享”，选择主控电脑并粘贴。</p></div></li>
                <li><span>3</span><div><strong>设置屏幕方向</strong><p>连接成功后选择左、右、上、下，与真实摆放保持一致。</p></div></li>
              </ol>
              <div className="guide-note">软件可以最小化到后台运行，不需要一直停留在当前窗口。</div>
            </aside>
          </section>
        ) : (
          <section className="workspace-stack">
            <section className="panel connect-card">
              <div className="panel-heading horizontal">
                <div>
                  <span className="section-kicker">主控电脑</span>
                  <h2>连接另一台电脑</h2>
                  <p>粘贴被控电脑生成的连接密钥。无需填写 IP、端口或路由器配置。</p>
                </div>
                <button className="text-button" disabled={busy} onClick={() => void chooseRole('client')}>切换为被控</button>
              </div>
              <div className="connect-input-row">
                <textarea
                  className="connect-textarea"
                  value={keyInput}
                  onChange={(event) => setKeyInput(event.target.value)}
                  spellCheck={false}
                  placeholder="粘贴 SFAI1- 开头的连接密钥"
                />
                <button className="button primary connect-button" disabled={busy || !keyInput.trim()} onClick={() => void connectByKey()}>
                  {busy ? '正在连接…' : '建立连接'}
                </button>
              </div>
            </section>

            <section className="panel devices-panel">
              <div className="panel-heading horizontal devices-heading">
                <div>
                  <span className="section-kicker">设备</span>
                  <h2>已连接电脑</h2>
                </div>
                <span className="device-count">{remotes.length} 台</span>
              </div>

              {remotes.length === 0 ? (
                <div className="empty-state">
                  <ComputerIcon />
                  <strong>还没有连接被控电脑</strong>
                  <p>在另一台电脑选择“被控电脑”，复制连接密钥后粘贴到上方。</p>
                </div>
              ) : (
                <div className="device-list">
                  {remotes.map((device) => (
                    <article className="device-card" key={device.id}>
                      <div className="device-summary">
                        <ComputerIcon />
                        <div className="device-copy">
                          <div className="device-title-line">
                            <strong>{device.name}</strong>
                            <span className={`device-state ${device.inputReady ? 'ready' : ''}`}><i />{device.inputReady ? '可控制' : '等待连接'}</span>
                          </div>
                          <p>{platformLabel(device.platform)} · {device.screens.length} 个屏幕 · 加密连接</p>
                        </div>
                        <button className="remove-button" onClick={() => void removeRemote(device.id)}>删除</button>
                      </div>
                      <div className="screen-placement">
                        <div>
                          <strong>屏幕位置</strong>
                          <p>选择被控电脑相对主控屏幕的位置，鼠标从对应边缘推出即可切换。</p>
                        </div>
                        <DirectionButtons disabled={busy} onSelect={(position) => void placeRemote(device.id, position)} />
                      </div>
                    </article>
                  ))}
                </div>
              )}
            </section>
          </section>
        )}

        {message ? <div className={`toast ${message.includes('失败') || message.includes('invalid') ? 'error' : ''}`}>{message}</div> : null}

        <footer className="app-footer">
          <div><BrandMark compact /><span>{PRODUCT} · v{APP_VERSION}</span></div>
          <span>{local?.name ?? '本机'} · 安全连接已启用</span>
        </footer>
      </main>
    </div>
  )
}
