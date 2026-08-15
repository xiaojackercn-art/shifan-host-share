#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def patch_backend(root: Path) -> None:
    path = root / "src-tauri" / "src" / "lib.rs"
    text = path.read_text(encoding="utf-8")

    old = '''#[tauri::command]
fn wan_connection_info(
    state: tauri::State<'_, AppRuntime>,
) -> Result<quic_transport::WanConnectionInfo, String> {
    state.start_discovery()?;
    let transport = state
        .quic_transport_handle()
        .ok_or_else(|| "公网连接服务还没有启动，请稍后重试。".to_string())?;
    Ok(transport.connection_info())
}

#[tauri::command]
fn probe_wan_peer('''
    new = '''#[tauri::command]
fn wan_connection_info(
    state: tauri::State<'_, AppRuntime>,
) -> Result<quic_transport::WanConnectionInfo, String> {
    state.start_discovery()?;
    let transport = state
        .quic_transport_handle()
        .ok_or_else(|| "公网连接服务还没有启动，请稍后重试。".to_string())?;
    Ok(transport.connection_info())
}

#[tauri::command]
fn regenerate_wan_connection_key(
    state: tauri::State<'_, AppRuntime>,
) -> Result<AppStateSnapshot, String> {
    let updated_layout = {
        let mut layout = state
            .layout
            .lock()
            .map_err(|_| "layout state lock poisoned".to_string())?;
        if layout.machine_role != "client" {
            return Err("只有被控电脑可以重新生成连接密钥。".to_string());
        }
        // pair_secret is backend-owned and intentionally ignored by save_layout.
        // Rotate it here so the operation is real and atomic instead of a UI-only refresh.
        layout.pair_secret = default_pair_secret();
        layout.paired_controllers.clear();
        layout.clone()
    };
    write_layout_to_disk(&state.config_path, &updated_layout)?;
    if let Ok(mut challenge) = state.pairing_challenge.lock() {
        *challenge = None;
    }
    if let Ok(mut runtime) = state.runtime.lock() {
        runtime.pairing = state.pairing_status_for_layout(&updated_layout);
    }
    log::info!("WAN connection capability rotated; previous connection keys are revoked");
    Ok(state.snapshot())
}

#[tauri::command]
fn probe_wan_peer('''
    text = replace_once(text, old, new, "real backend WAN key rotation command")

    text = replace_once(
        text,
        '''            scan_lan_peers,
            wan_connection_info,
            probe_wan_peer,''',
        '''            scan_lan_peers,
            wan_connection_info,
            regenerate_wan_connection_key,
            probe_wan_peer,''',
        "register WAN key rotation command",
    )

    old_window = '''    let window = WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
        .title("视饭AI:主机共享")
        .inner_size(1480.0, 960.0)
        .min_inner_size(1200.0, 760.0)
        .resizable(true)
        .theme(Some(tauri::Theme::Dark))
        .visible(false)
        .build()
        .map_err(|error| format!("failed to create main window: {error}"))?;
'''
    new_window = '''    let mut builder = WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
        .title("视饭AI:主机共享")
        .inner_size(1360.0, 880.0)
        .min_inner_size(1080.0, 700.0)
        .resizable(true)
        .theme(Some(tauri::Theme::Light))
        .visible(false);
    if let Some(icon) = app.default_window_icon().cloned() {
        builder = builder
            .icon(icon)
            .map_err(|error| format!("failed to apply product window icon: {error}"))?;
    }
    let window = builder
        .build()
        .map_err(|error| format!("failed to create main window: {error}"))?;
'''
    text = replace_once(text, old_window, new_window, "explicit product window icon")

    path.write_text(text, encoding="utf-8")


def patch_frontend(root: Path) -> None:
    path = root / "src" / "App.tsx"
    text = path.read_text(encoding="utf-8")

    old_brand = '''function BrandMark({ compact = false }: { compact?: boolean }) {
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
'''
    new_brand = '''function BrandMark({ compact = false }: { compact?: boolean }) {
  return (
    <span className={`brand-mark ${compact ? 'compact' : ''}`} aria-hidden="true">
      <img src="/app-icon.png" alt="" draggable={false} />
    </span>
  )
}
'''
    text = replace_once(text, old_brand, new_brand, "use actual product logo in UI")

    random_helper = '''function randomHex(byteCount: number) {
  const bytes = new Uint8Array(byteCount)
  crypto.getRandomValues(bytes)
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('')
}
'''
    text = replace_once(text, random_helper, "", "remove ineffective frontend secret generator")

    decode_tail = '''function decodeBase64Url(value: string) {
  const padded = value.replace(/-/g, '+').replace(/_/g, '/') + '==='.slice((value.length + 3) % 4)
  const binary = atob(padded)
  return Uint8Array.from(binary, (char) => char.charCodeAt(0))
}
'''
    decode_replacement = decode_tail + '''
function keyFingerprint(value: string) {
  if (!value) return ''
  let hash = 0x811c9dc5
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index)
    hash = Math.imul(hash, 0x01000193)
  }
  return (hash >>> 0).toString(16).padStart(8, '0').toUpperCase()
}
'''
    text = replace_once(text, decode_tail, decode_replacement, "connection key fingerprint helper")

    state_anchor = '''  const [message, setMessage] = useState('')
  const [copied, setCopied] = useState(false)
'''
    state_replacement = '''  const [message, setMessage] = useState('')
  const [copied, setCopied] = useState(false)
  const [keyGeneratedAt, setKeyGeneratedAt] = useState('')
'''
    text = replace_once(text, state_anchor, state_replacement, "key generation status state")

    old_regen = '''  async function regenerateConnectionKey() {
    if (role !== 'client' || !layout || !runtime) return
    setBusy(true)
    setMessage('正在生成新的连接授权…')
    try {
      const state = await saveLayout({
        ...layout,
        pairSecret: randomHex(32),
      })
      setSnapshot(state)
      setRuntime(state.runtime)
      const network = await invoke<WanConnectionInfo>('wan_connection_info')
      const key = makeConnectionKey(state.layout, state.runtime, network)
      setConnectionKey(key)
      setCopied(false)
      setMessage(
        key
          ? '新的连接密钥已生成，之前的连接密钥已失效。'
          : '新的连接授权已生成，正在等待公网中继就绪；就绪后密钥会自动显示。',
      )
    } catch (error) {
      setMessage(`重新生成连接密钥失败：${String(error)}`)
    } finally {
      setBusy(false)
    }
  }
'''
    new_regen = '''  async function regenerateConnectionKey() {
    if (role !== 'client' || !runtime) return
    setBusy(true)
    setMessage('正在撤销旧密钥并生成新的连接授权…')
    try {
      const previousKey = connectionKey
      const state = await invoke<AppStateSnapshot>('regenerate_wan_connection_key')
      setSnapshot(state)
      setRuntime(state.runtime)
      const network = await invoke<WanConnectionInfo>('wan_connection_info')
      const key = makeConnectionKey(state.layout, state.runtime, network)
      setConnectionKey(key)
      setCopied(false)
      setKeyGeneratedAt(new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }))
      if (key && key === previousKey) {
        throw new Error('后端返回的连接密钥没有发生变化，请重新启动软件后再试。')
      }
      setMessage(
        key
          ? '新密钥已生成。旧密钥已立即失效，请把当前密钥重新复制到主控电脑。'
          : '新授权已生成，正在等待公网通道就绪；就绪后密钥会自动显示。',
      )
    } catch (error) {
      setMessage(`重新生成连接密钥失败：${String(error)}`)
    } finally {
      setBusy(false)
    }
  }
'''
    text = replace_once(text, old_regen, new_regen, "frontend calls real backend key rotation")

    old_key_area = '''              <label className="field-label" htmlFor="connection-key">本机连接密钥</label>
              <textarea id="connection-key" className="key-textarea" value={connectionKey} readOnly spellCheck={false} placeholder="正在生成连接密钥…" />
              <div className="button-row">'''
    new_key_area = '''              <label className="field-label" htmlFor="connection-key">本机连接密钥</label>
              <textarea id="connection-key" className="key-textarea" value={connectionKey} readOnly spellCheck={false} placeholder="正在生成连接密钥…" />
              <div className="key-meta" aria-live="polite">
                <span>协议 v2</span>
                <span>{connectionKey ? `指纹 ${keyFingerprint(connectionKey)}` : '等待公网通道'}</span>
                {keyGeneratedAt ? <span>更新 {keyGeneratedAt}</span> : null}
              </div>
              <div className="button-row">'''
    text = replace_once(text, old_key_area, new_key_area, "visible key generation fingerprint")

    text = text.replace(
        '支持 Windows 与 macOS 跨网络连接。无需公网 IP、端口映射或同一 Wi‑Fi，连接完成后把鼠标推过屏幕边缘即可切换，键盘会跟随当前电脑。',
        '支持 Windows 与 macOS 跨网络连接。优先建立低延迟直连，无法直连时自动回退公网中继；连接后把鼠标推过屏幕边缘即可切换，键盘同步跟随。',
        1,
    )
    text = text.replace('<span>低延迟鼠标通道</span>', '<span>直连优先</span>', 1)
    text = text.replace('<span>键盘跟随</span>', '<span>键鼠同步</span>', 1)

    path.write_text(text, encoding="utf-8")


def patch_css(root: Path) -> None:
    path = root / "src" / "index.css"
    text = path.read_text(encoding="utf-8")

    old_brand_css = '''.brand-mark {
  display: inline-grid;
  place-items: center;
  width: 66px;
  height: 66px;
  flex: none;
  border-radius: 18px;
  background: linear-gradient(145deg, #175cd3, #0b3d91);
  box-shadow: 0 12px 28px rgba(37, 99, 235, .22), inset 0 1px 0 rgba(255,255,255,.22);
}
.brand-mark.compact { width: 38px; height: 38px; border-radius: 10px; box-shadow: 0 7px 18px rgba(37,99,235,.18); }
.brand-mark svg { width: 72%; height: 72%; overflow: visible; }
.brand-mark svg rect,
.brand-mark svg path {
  fill: none;
  stroke: #ffffff;
  stroke-width: 2.5;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.brand-mark svg .brand-mark-secondary { stroke: #cde4ff; }
.brand-mark svg .brand-mark-link { stroke: #62e0c5; stroke-width: 2.8; }
'''
    new_brand_css = '''.brand-mark {
  display: inline-grid;
  place-items: center;
  width: 66px;
  height: 66px;
  flex: none;
  border-radius: 18px;
  background: #fff;
  box-shadow: 0 12px 30px rgba(32, 67, 121, .16), 0 0 0 1px rgba(30, 72, 138, .08);
  overflow: hidden;
}
.brand-mark.compact { width: 40px; height: 40px; border-radius: 11px; box-shadow: 0 7px 18px rgba(31,72,132,.14), 0 0 0 1px rgba(30,72,138,.07); }
.brand-mark img { display: block; width: 100%; height: 100%; object-fit: cover; user-select: none; -webkit-user-drag: none; }
'''
    text = replace_once(text, old_brand_css, new_brand_css, "actual product logo styling")

    text = text.replace('min-height: 244px;', 'min-height: 220px;', 1)
    text = text.replace('padding: 34px 38px;', 'padding: 30px 34px;', 1)
    text = text.replace('box-shadow: 0 14px 36px rgba(28, 47, 77, .07);', 'box-shadow: 0 18px 48px rgba(28, 47, 77, .08);', 1)

    key_anchor = '''.key-textarea { min-height: 138px; padding: 14px; font-family: "Cascadia Mono", "SFMono-Regular", Consolas, monospace; font-size: 11.5px; line-height: 1.6; word-break: break-all; }
.button-row { display: flex; gap: 10px; margin-top: 12px; }
'''
    key_replacement = '''.key-textarea { min-height: 138px; padding: 14px; font-family: "Cascadia Mono", "SFMono-Regular", Consolas, monospace; font-size: 11.5px; line-height: 1.6; word-break: break-all; }
.key-meta { display: flex; flex-wrap: wrap; gap: 7px; margin-top: 9px; min-height: 24px; }
.key-meta span { padding: 5px 8px; border: 1px solid #dfe7f1; border-radius: 999px; background: #f7f9fc; color: #69778d; font-size: 10.5px; font-weight: 650; letter-spacing: .01em; }
.button-row { display: flex; gap: 10px; margin-top: 12px; }
'''
    text = replace_once(text, key_anchor, key_replacement, "connection key metadata styling")

    path.write_text(text, encoding="utf-8")


def patch_input(root: Path) -> None:
    path = root / "src-tauri" / "src" / "input.rs"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "const MOUSE_MOVE_SEND_INTERVAL_MS: u64 = 4;\nconst DRAG_MOVE_SEND_INTERVAL_MS: u64 = 4;",
        "const MOUSE_MOVE_SEND_INTERVAL_MS: u64 = 1;\nconst DRAG_MOVE_SEND_INTERVAL_MS: u64 = 1;",
        "1ms realtime pointer sampling",
    )
    path.write_text(text, encoding="utf-8")

    win_path = root / "src-tauri" / "src" / "windows_input.rs"
    win = win_path.read_text(encoding="utf-8")
    old = '''pub fn inject_key(key_code: u16, down: bool) {
    use windows_sys::Win32::UI::Input::KeyboardAndMouse::{
        MapVirtualKeyW, SendInput, INPUT, INPUT_0, INPUT_KEYBOARD, KEYBDINPUT,
        KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP, KEYEVENTF_SCANCODE, MAPVK_VK_TO_VSC,
    };

    let mut dw_flags = if down { 0 } else { KEYEVENTF_KEYUP };
    if is_extended_key_vk(key_code) {
        dw_flags |= KEYEVENTF_EXTENDEDKEY;
    }

    let scan = unsafe { MapVirtualKeyW(key_code as u32, MAPVK_VK_TO_VSC) } as u16;
    let (w_vk, w_scan, flags) = if scan != 0 {
        (0, scan, dw_flags | KEYEVENTF_SCANCODE)
    } else {
        (key_code, 0, dw_flags)
    };

    let input = INPUT {
        r#type: INPUT_KEYBOARD,
        Anonymous: INPUT_0 {
            ki: KEYBDINPUT {
                wVk: w_vk,
                wScan: w_scan,
                dwFlags: flags,
                time: 0,
                dwExtraInfo: 0,
            },
        },
    };
    unsafe {
        if SendInput(1, &input, std::mem::size_of::<INPUT>() as i32) == 0 {
            note_injection_refused("key", windows_sys::Win32::Foundation::GetLastError());
        }
    }
}
'''
    new = '''pub fn inject_key(key_code: u16, down: bool) {
    use windows_sys::Win32::UI::Input::KeyboardAndMouse::{
        MapVirtualKeyW, SendInput, INPUT, INPUT_0, INPUT_KEYBOARD, KEYBDINPUT,
        KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP, KEYEVENTF_SCANCODE, MAPVK_VK_TO_VSC,
    };

    let mut base_flags = if down { 0 } else { KEYEVENTF_KEYUP };
    if is_extended_key_vk(key_code) {
        base_flags |= KEYEVENTF_EXTENDEDKEY;
    }
    let scan = unsafe { MapVirtualKeyW(key_code as u32, MAPVK_VK_TO_VSC) } as u16;

    // Virtual-key injection is the Windows-compatible default for normal desktop
    // applications. alpha.5 forced every key through SCANCODE-only mode, which
    // made keyboard control fail on some real Windows machines even while mouse
    // input kept working. Preserve the scan code as metadata, then fall back to
    // physical scan-code injection only if the primary SendInput call is refused.
    let primary = INPUT {
        r#type: INPUT_KEYBOARD,
        Anonymous: INPUT_0 {
            ki: KEYBDINPUT {
                wVk: key_code,
                wScan: scan,
                dwFlags: base_flags,
                time: 0,
                dwExtraInfo: 0,
            },
        },
    };

    unsafe {
        if SendInput(1, &primary, std::mem::size_of::<INPUT>() as i32) != 0 {
            return;
        }

        let primary_error = windows_sys::Win32::Foundation::GetLastError();
        if scan != 0 {
            let fallback = INPUT {
                r#type: INPUT_KEYBOARD,
                Anonymous: INPUT_0 {
                    ki: KEYBDINPUT {
                        wVk: 0,
                        wScan: scan,
                        dwFlags: base_flags | KEYEVENTF_SCANCODE,
                        time: 0,
                        dwExtraInfo: 0,
                    },
                },
            };
            if SendInput(1, &fallback, std::mem::size_of::<INPUT>() as i32) != 0 {
                log::debug!("keyboard virtual-key injection failed but scan-code fallback succeeded");
                return;
            }
        }
        note_injection_refused("key", primary_error);
    }
}
'''
    win = replace_once(win, old, new, "Windows virtual-key first keyboard injection")
    win_path.write_text(win, encoding="utf-8")


def patch_transport(root: Path) -> None:
    path = root / "src-tauri" / "src" / "quic_transport.rs"
    text = path.read_text(encoding="utf-8")

    old_helper = '''fn endpoint_addr_for_peer(peer: &PeerEndpoint) -> Result<EndpointAddr, String> {
    let endpoint_id = EndpointId::from_z32(peer.public_key.trim())
        .map_err(|error| format!("invalid WAN endpoint id: {error}"))?;
    let mut endpoint_addr = EndpointAddr::new(endpoint_id);

    if let Some(ticket) = peer.addr.strip_prefix("wan:") {
        let mut parts = ticket.split('|');
        let embedded_id = parts.next().unwrap_or_default().trim();
        if !embedded_id.is_empty() && embedded_id != peer.public_key.trim() {
            return Err("连接密钥中的设备身份不一致，请重新生成密钥。".to_string());
        }
        for part in parts {
            if let Some(raw) = part.strip_prefix("r=") {
                for relay in raw.split(',').map(str::trim).filter(|value| !value.is_empty()) {
                    let relay_url = relay
                        .parse::<RelayUrl>()
                        .map_err(|error| format!("连接密钥中的中继地址无效: {error}"))?;
                    endpoint_addr = endpoint_addr.with_relay_url(relay_url);
                }
            } else if let Some(raw) = part.strip_prefix("a=") {
                for addr in raw.split(',').map(str::trim).filter(|value| !value.is_empty()) {
                    let socket_addr = addr
                        .parse::<SocketAddr>()
                        .map_err(|error| format!("连接密钥中的直连地址无效: {error}"))?;
                    endpoint_addr = endpoint_addr.with_ip_addr(socket_addr);
                }
            }
        }
    }

    Ok(endpoint_addr)
}
'''
    new_helper = old_helper + '''
fn direct_endpoint_addr_for_peer(peer: &PeerEndpoint) -> Result<Option<EndpointAddr>, String> {
    let endpoint_id = EndpointId::from_z32(peer.public_key.trim())
        .map_err(|error| format!("invalid WAN endpoint id: {error}"))?;
    let Some(ticket) = peer.addr.strip_prefix("wan:") else {
        return Ok(None);
    };
    let mut endpoint_addr = EndpointAddr::new(endpoint_id);
    let mut has_direct = false;
    for part in ticket.split('|').skip(1) {
        if let Some(raw) = part.strip_prefix("a=") {
            for addr in raw.split(',').map(str::trim).filter(|value| !value.is_empty()) {
                let socket_addr = addr
                    .parse::<SocketAddr>()
                    .map_err(|error| format!("连接密钥中的直连地址无效: {error}"))?;
                endpoint_addr = endpoint_addr.with_ip_addr(socket_addr);
                has_direct = true;
            }
        }
    }
    Ok(has_direct.then_some(endpoint_addr))
}
'''
    text = replace_once(text, old_helper, new_helper, "direct-only endpoint helper")

    old_ensure = '''async fn ensure_connection(
    endpoint: &Endpoint,
    connections: &ConnectionMap,
    peer: &PeerEndpoint,
) -> Result<iroh::endpoint::Connection, String> {
    let endpoint_addr = endpoint_addr_for_peer(peer)?;
    let key = endpoint_addr.id.to_z32();
    if let Some(connection) = connections
        .lock()
        .ok()
        .and_then(|connections| connections.get(&key).cloned())
        .filter(|connection| connection.close_reason().is_none())
    {
        return Ok(connection);
    }

    let connection = tokio::time::timeout(CONNECT_TIMEOUT, endpoint.connect(endpoint_addr, ALPN))
        .await
        .map_err(|_| format!("连接被控电脑 {key} 超时，请检查两台电脑的网络后重试。"))?
        .map_err(|error| {
            let detail = error.to_string();
            if detail.contains("No addressing information available") {
                "无法找到被控电脑的公网地址。请在被控电脑等待“公网连接已就绪”后，重新生成连接密钥再连接。".to_string()
            } else {
                format!("连接被控电脑 {key} 失败：{detail}")
            }
        })?;

    if let Ok(mut map) = connections.lock() {
        map.insert(key.clone(), connection.clone());
    }
    Ok(connection)
}
'''
    new_ensure = '''async fn ensure_connection(
    endpoint: &Endpoint,
    connections: &ConnectionMap,
    peer: &PeerEndpoint,
) -> Result<iroh::endpoint::Connection, String> {
    let endpoint_addr = endpoint_addr_for_peer(peer)?;
    let key = endpoint_addr.id.to_z32();
    if let Some(connection) = connections
        .lock()
        .ok()
        .and_then(|connections| connections.get(&key).cloned())
        .filter(|connection| connection.close_reason().is_none())
    {
        return Ok(connection);
    }

    // Prefer a direct socket path briefly before allowing relay fallback. On the
    // same LAN (and on WANs where NAT traversal already exposed a usable direct
    // candidate) this avoids beginning the interactive session on a distant
    // public relay. If direct is unavailable, fall back quickly to the full Iroh
    // EndpointAddr so connectivity is preserved.
    if let Some(direct_addr) = direct_endpoint_addr_for_peer(peer)? {
        if let Ok(Ok(connection)) = tokio::time::timeout(
            Duration::from_millis(650),
            endpoint.connect(direct_addr, ALPN),
        )
        .await
        {
            log::info!("WAN peer {key} connected on direct-first low-latency path");
            if let Ok(mut map) = connections.lock() {
                map.insert(key.clone(), connection.clone());
            }
            return Ok(connection);
        }
    }

    let connection = tokio::time::timeout(CONNECT_TIMEOUT, endpoint.connect(endpoint_addr, ALPN))
        .await
        .map_err(|_| format!("连接被控电脑 {key} 超时，请检查两台电脑的网络后重试。"))?
        .map_err(|error| {
            let detail = error.to_string();
            if detail.contains("No addressing information available") {
                "无法找到被控电脑的公网地址。请在被控电脑等待“公网连接已就绪”后，重新生成连接密钥再连接。".to_string()
            } else {
                format!("连接被控电脑 {key} 失败：{detail}")
            }
        })?;

    if let Ok(mut map) = connections.lock() {
        map.insert(key.clone(), connection.clone());
    }
    Ok(connection)
}
'''
    text = replace_once(text, old_ensure, new_ensure, "direct-first low latency dialing")
    path.write_text(text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()

    patch_backend(root)
    patch_frontend(root)
    patch_css(root)
    patch_input(root)
    patch_transport(root)
    print("alpha.6 production input and product polish overlay applied")


if __name__ == "__main__":
    main()
