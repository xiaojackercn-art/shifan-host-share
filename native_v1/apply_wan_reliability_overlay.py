#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def patch_transport(root: Path) -> None:
    path = root / "src-tauri" / "src" / "quic_transport.rs"
    text = path.read_text(encoding="utf-8")

    text = replace_once(
        text,
        "use iroh::{endpoint::presets, Endpoint, EndpointId, SecretKey};",
        "use iroh::{endpoint::presets, Endpoint, EndpointAddr, EndpointId, RelayUrl, SecretKey};\nuse serde::Serialize;",
        "Iroh imports",
    )

    marker = '''#[derive(Clone, Debug)]
pub struct PeerEndpoint {
    pub addr: String,
    pub public_key: String,
    pub protocol_version: u16,
}
'''
    replacement = marker + '''
#[derive(Clone, Debug, Default, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct WanConnectionInfo {
    pub endpoint_id: String,
    pub relay_urls: Vec<String>,
    pub direct_addresses: Vec<String>,
    pub ready: bool,
}
'''
    text = replace_once(text, marker, replacement, "WAN connection info model")

    text = replace_once(
        text,
        '''pub struct TransportHandle {
    commands: tokio_mpsc::UnboundedSender<TransportCommand>,
    port: u16,
    public_key: String,
    peer_health: HealthMap,
    latest_datagrams: LatestDatagramMap,
}''',
        '''pub struct TransportHandle {
    commands: tokio_mpsc::UnboundedSender<TransportCommand>,
    port: u16,
    public_key: String,
    connection_info: Arc<Mutex<WanConnectionInfo>>,
    peer_health: HealthMap,
    latest_datagrams: LatestDatagramMap,
}''',
        "TransportHandle WAN connection info",
    )

    text = replace_once(
        text,
        '''    pub fn public_key(&self) -> &str {
        &self.public_key
    }

    pub fn peer(&self, addr: String, public_key: String, protocol_version: u16) -> PeerEndpoint {''',
        '''    pub fn public_key(&self) -> &str {
        &self.public_key
    }

    pub fn connection_info(&self) -> WanConnectionInfo {
        self.connection_info
            .lock()
            .map(|info| info.clone())
            .unwrap_or_default()
    }

    pub fn peer(&self, addr: String, public_key: String, protocol_version: u16) -> PeerEndpoint {''',
        "TransportHandle WAN connection info getter",
    )

    marker = '''pub fn validate_endpoint_id(value: &str) -> Result<(), String> {
    EndpointId::from_z32(value.trim())
        .map(|_| ())
        .map_err(|error| format!("invalid WAN endpoint id: {error}"))
}
'''
    replacement = marker + '''
pub fn format_wan_peer_addr(
    endpoint_id: &str,
    relay_urls: &[String],
    direct_addresses: &[String],
) -> String {
    let relays = relay_urls
        .iter()
        .map(|value| value.trim())
        .filter(|value| !value.is_empty())
        .collect::<Vec<_>>()
        .join(",");
    let direct = direct_addresses
        .iter()
        .map(|value| value.trim())
        .filter(|value| !value.is_empty())
        .collect::<Vec<_>>()
        .join(",");
    format!("wan:{}|r={}|a={}", endpoint_id.trim(), relays, direct)
}

fn endpoint_addr_for_peer(peer: &PeerEndpoint) -> Result<EndpointAddr, String> {
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
    text = replace_once(text, marker, replacement, "explicit WAN EndpointAddr ticket")

    text = replace_once(
        text,
        '''    let peer_health: HealthMap = Arc::new(Mutex::new(HashMap::new()));
    let latest_datagrams: LatestDatagramMap = Arc::new(Mutex::new(HashMap::new()));
    let loop_health = Arc::clone(&peer_health);
    let loop_latest = Arc::clone(&latest_datagrams);''',
        '''    let peer_health: HealthMap = Arc::new(Mutex::new(HashMap::new()));
    let latest_datagrams: LatestDatagramMap = Arc::new(Mutex::new(HashMap::new()));
    let connection_info = Arc::new(Mutex::new(WanConnectionInfo::default()));
    let loop_health = Arc::clone(&peer_health);
    let loop_latest = Arc::clone(&latest_datagrams);
    let loop_connection_info = Arc::clone(&connection_info);''',
        "shared WAN address state",
    )

    text = replace_once(
        text,
        '''                loop_health,
                loop_latest,
                ready_tx,''',
        '''                loop_health,
                loop_latest,
                loop_connection_info,
                ready_tx,''',
        "run transport WAN address state",
    )

    text = replace_once(
        text,
        '''        port: ready.port,
        public_key: ready.public_key,
        peer_health,
        latest_datagrams,''',
        '''        port: ready.port,
        public_key: ready.public_key,
        connection_info,
        peer_health,
        latest_datagrams,''',
        "transport handle WAN state",
    )

    text = replace_once(
        text,
        '''    health: HealthMap,
    latest_datagrams: LatestDatagramMap,
    ready_tx: mpsc::Sender<Result<ReadyTransport, String>>,''',
        '''    health: HealthMap,
    latest_datagrams: LatestDatagramMap,
    connection_info: Arc<Mutex<WanConnectionInfo>>,
    ready_tx: mpsc::Sender<Result<ReadyTransport, String>>,''',
        "run transport connection info parameter",
    )

    text = replace_once(
        text,
        '''    if tokio::time::timeout(ONLINE_WAIT, endpoint.online()).await.is_err() {
        log::warn!("WAN relay registration did not complete within {}s", ONLINE_WAIT.as_secs());
    }

    let port = endpoint''',
        '''    if tokio::time::timeout(ONLINE_WAIT, endpoint.online()).await.is_err() {
        log::warn!("WAN relay registration did not complete within {}s", ONLINE_WAIT.as_secs());
    }

    refresh_connection_info(&endpoint, &connection_info);

    let port = endpoint''',
        "initial WAN address snapshot",
    )

    text = replace_once(
        text,
        '''    let connections: ConnectionMap = Arc::new(Mutex::new(HashMap::new()));

    loop {
        tokio::select! {''',
        '''    let connections: ConnectionMap = Arc::new(Mutex::new(HashMap::new()));
    let mut address_refresh = tokio::time::interval(Duration::from_secs(1));
    address_refresh.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);

    loop {
        tokio::select! {
            _ = address_refresh.tick() => {
                refresh_connection_info(&endpoint, &connection_info);
            }''',
        "continuously refresh WAN address snapshot",
    )

    marker = '''async fn send_datagram_now(
    endpoint: &Endpoint,'''
    replacement = '''fn current_connection_info(endpoint: &Endpoint) -> WanConnectionInfo {
    let addr = endpoint.addr();
    let mut relay_urls = addr
        .relay_urls()
        .map(ToString::to_string)
        .collect::<Vec<_>>();
    relay_urls.sort();
    relay_urls.dedup();
    let mut direct_addresses = addr
        .ip_addrs()
        .map(ToString::to_string)
        .collect::<Vec<_>>();
    direct_addresses.sort();
    direct_addresses.dedup();
    WanConnectionInfo {
        endpoint_id: endpoint.id().to_z32(),
        ready: !relay_urls.is_empty(),
        relay_urls,
        direct_addresses,
    }
}

fn refresh_connection_info(endpoint: &Endpoint, shared: &Arc<Mutex<WanConnectionInfo>>) {
    let next = current_connection_info(endpoint);
    if let Ok(mut current) = shared.lock() {
        *current = next;
    }
}

async fn send_datagram_now(
    endpoint: &Endpoint,'''
    text = replace_once(text, marker, replacement, "WAN address snapshot helpers")

    old_ensure = '''async fn ensure_connection(
    endpoint: &Endpoint,
    connections: &ConnectionMap,
    peer: &PeerEndpoint,
) -> Result<iroh::endpoint::Connection, String> {
    let endpoint_id = EndpointId::from_z32(peer.public_key.trim())
        .map_err(|error| format!("invalid WAN endpoint id: {error}"))?;
    let key = endpoint_id.to_z32();
    if let Some(connection) = connections
        .lock()
        .ok()
        .and_then(|connections| connections.get(&key).cloned())
        .filter(|connection| connection.close_reason().is_none())
    {
        return Ok(connection);
    }

    let connection = tokio::time::timeout(CONNECT_TIMEOUT, endpoint.connect(endpoint_id, ALPN))
        .await
        .map_err(|_| format!("WAN connect to {key} timed out"))?
        .map_err(|error| format!("WAN connect to {key} failed: {error}"))?;

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
    text = replace_once(text, old_ensure, new_ensure, "explicit WAN EndpointAddr dialing")

    path.write_text(text, encoding="utf-8")


def patch_input_targets(root: Path) -> None:
    path = root / "src-tauri" / "src" / "input.rs"
    text = path.read_text(encoding="utf-8")
    old = '''fn wan_target_credentials(device: &Device) -> Option<(String, String, String)> {
    if device.source != "wan-key" {
        return None;
    }
    let rest = device.host.strip_prefix("wan://")?;
    let mut parts = rest.splitn(3, '/');
    let endpoint_id = parts.next()?.trim();
    let cluster_id = parts.next()?.trim();
    let pair_secret = parts.next()?.trim();
    if endpoint_id.is_empty() || cluster_id.is_empty() || pair_secret.is_empty() {
        return None;
    }
    Some((endpoint_id.to_string(), cluster_id.to_string(), pair_secret.to_string()))
}
'''
    new = '''fn wan_target_credentials(device: &Device) -> Option<(String, String, String)> {
    if device.source != "wan-key" {
        return None;
    }

    let rest = device.host.strip_prefix("wan://")?;
    let mut parts = rest.splitn(3, '/');
    let endpoint_id = parts.next()?.trim();
    let cluster_id = parts.next()?.trim();
    let pair_and_route = parts.next()?.trim();
    let pair_secret = pair_and_route.split('|').next().unwrap_or(pair_and_route).trim();
    if endpoint_id.is_empty() || cluster_id.is_empty() || pair_secret.is_empty() {
        return None;
    }
    Some((endpoint_id.to_string(), cluster_id.to_string(), pair_secret.to_string()))
}

fn wan_target_addr(device: &Device, endpoint_id: &str) -> String {
    let Some(rest) = device.host.strip_prefix("wan://") else {
        return format!("wan:{endpoint_id}");
    };
    let mut parts = rest.splitn(3, '/');
    let _ = parts.next();
    let _ = parts.next();
    let pair_and_route = parts.next().unwrap_or_default();
    if let Some((_, route)) = pair_and_route.split_once('|') {
        return format!("wan:{endpoint_id}|{route}");
    }
    format!("wan:{endpoint_id}")
}
'''
    text = replace_once(text, old, new, "WAN target persisted credentials")

    text = replace_once(
        text,
        '''            .map(|(endpoint_id, _, _)| format!("wan:{endpoint_id}"))
            .unwrap_or_else(|| format!("{}:{}", device.host, quic_port));''',
        '''            .map(|(endpoint_id, _, _)| wan_target_addr(device, endpoint_id))
            .unwrap_or_else(|| format!("{}:{}", device.host, quic_port));''',
        "WAN target explicit address ticket",
    )
    path.write_text(text, encoding="utf-8")


def patch_backend_commands(root: Path) -> None:
    path = root / "src-tauri" / "src" / "lib.rs"
    text = path.read_text(encoding="utf-8")

    old_probe = '''#[tauri::command]
fn probe_wan_peer(
    endpoint_id: String,
    state: tauri::State<'_, AppRuntime>,
) -> Result<(), String> {
    state.start_discovery()?;
    quic_transport::validate_endpoint_id(endpoint_id.trim())?;
    let transport = state
        .quic_transport_handle()
        .ok_or_else(|| "公网连接服务还没有启动，请稍后重试。".to_string())?;
    let peer = transport.peer(
        "wan".to_string(),
        endpoint_id.trim().to_string(),
        quic_transport::PROTOCOL_VERSION,
    );
    transport.probe(peer)
}
'''
    new_probe = '''#[tauri::command]
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
fn probe_wan_peer(
    endpoint_id: String,
    relay_urls: Vec<String>,
    direct_addresses: Vec<String>,
    state: tauri::State<'_, AppRuntime>,
) -> Result<(), String> {
    state.start_discovery()?;
    quic_transport::validate_endpoint_id(endpoint_id.trim())?;
    if relay_urls.iter().all(|value| value.trim().is_empty())
        && direct_addresses.iter().all(|value| value.trim().is_empty())
    {
        return Err(
            "这是旧版或未就绪的连接密钥，没有携带可用公网地址。请在被控电脑重新生成连接密钥。"
                .to_string(),
        );
    }
    let transport = state
        .quic_transport_handle()
        .ok_or_else(|| "公网连接服务还没有启动，请稍后重试。".to_string())?;
    let peer = transport.peer(
        quic_transport::format_wan_peer_addr(
            endpoint_id.trim(),
            &relay_urls,
            &direct_addresses,
        ),
        endpoint_id.trim().to_string(),
        quic_transport::PROTOCOL_VERSION,
    );
    transport.probe(peer)
}
'''
    text = replace_once(text, old_probe, new_probe, "WAN connection info and explicit probe")

    text = replace_once(
        text,
        '''            scan_lan_peers,
            probe_wan_peer,
            probe_lan_peer,''',
        '''            scan_lan_peers,
            wan_connection_info,
            probe_wan_peer,
            probe_lan_peer,''',
        "register WAN connection info command",
    )
    path.write_text(text, encoding="utf-8")


def patch_frontend(root: Path) -> None:
    path = root / "src" / "App.tsx"
    text = path.read_text(encoding="utf-8")

    old_interface = '''interface ConnectionKeyPayload {
  version: 1
  endpointId: string
  name: string
  platform: string
  clusterId: string
  pairSecret: string
  screens: Screen[]
}
'''
    new_interface = '''interface ConnectionKeyPayload {
  version: number
  endpointId: string
  name: string
  platform: string
  clusterId: string
  pairSecret: string
  relayUrls: string[]
  directAddresses: string[]
  screens: Screen[]
}

interface WanConnectionInfo {
  endpointId: string
  relayUrls: string[]
  directAddresses: string[]
  ready: boolean
}
'''
    text = replace_once(text, old_interface, new_interface, "connection key v2 interface")

    decode_block = '''function decodeBase64Url(value: string) {
  const padded = value.replace(/-/g, '+').replace(/_/g, '/') + '==='.slice((value.length + 3) % 4)
  const binary = atob(padded)
  return Uint8Array.from(binary, (char) => char.charCodeAt(0))
}
'''
    decode_replacement = decode_block + '''
function randomHex(byteCount: number) {
  const bytes = new Uint8Array(byteCount)
  crypto.getRandomValues(bytes)
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('')
}
'''
    text = replace_once(text, decode_block, decode_replacement, "frontend random secret helper")

    old_make = '''function makeConnectionKey(layout: LayoutState, runtime: RuntimeStatus) {
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
'''
    new_make = '''function makeConnectionKey(layout: LayoutState, runtime: RuntimeStatus, network: WanConnectionInfo) {
  const local = localDevice(layout)
  const endpointId = network.endpointId.trim() || runtime.discovery.localPeer.transportPublicKey.trim()
  const relayUrls = network.relayUrls.map((value) => value.trim()).filter(Boolean)
  const directAddresses = network.directAddresses.map((value) => value.trim()).filter(Boolean)
  if (
    !local ||
    !network.ready ||
    relayUrls.length === 0 ||
    !endpointId ||
    !layout.clusterId.trim() ||
    !layout.pairSecret.trim()
  ) {
    return ''
  }
  const payload: ConnectionKeyPayload = {
    version: 2,
    endpointId,
    name: local.name,
    platform: local.platform,
    clusterId: layout.clusterId,
    pairSecret: layout.pairSecret,
    relayUrls,
    directAddresses,
    screens: local.screens,
  }
  return KEY_PREFIX + encodeBase64Url(new TextEncoder().encode(JSON.stringify(payload)))
}
'''
    text = replace_once(text, old_make, new_make, "make connection key with explicit WAN addresses")

    old_parse = '''function parseConnectionKey(key: string): ConnectionKeyPayload {
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
'''
    new_parse = '''function parseConnectionKey(key: string): ConnectionKeyPayload {
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
  if (parsed.version !== 2) {
    throw new Error('这是旧版连接密钥。请在被控电脑升级到当前版本后，点击“重新生成连接密钥”。')
  }
  if (
    !parsed.endpointId?.trim() ||
    !parsed.clusterId?.trim() ||
    !parsed.pairSecret?.trim() ||
    !Array.isArray(parsed.relayUrls) ||
    parsed.relayUrls.filter((value) => value?.trim()).length === 0 ||
    !Array.isArray(parsed.directAddresses) ||
    !Array.isArray(parsed.screens) ||
    parsed.screens.length === 0
  ) {
    throw new Error('连接密钥内容不完整，请在被控电脑重新生成后复制完整密钥。')
  }
  return parsed
}
'''
    text = replace_once(text, old_parse, new_parse, "parse connection key v2")

    text = replace_once(
        text,
        '    host: `wan://${endpointId}/${payload.clusterId}/${payload.pairSecret}`,',
        '    host: `wan://${endpointId}/${payload.clusterId}/${payload.pairSecret}|r=${payload.relayUrls.join(",")}|a=${payload.directAddresses.join(",")}`,',
        "persist WAN routing ticket in host",
    )

    text = replace_once(
        text,
        '''  const online = Boolean(runtime?.started && runtime.discovery.localPeer.transportPublicKey)''',
        '''  const online = Boolean(
    runtime?.started &&
      (role === 'client' ? connectionKey : runtime.discovery.localPeer.transportPublicKey),
  )''',
        "client readiness follows usable key",
    )

    old_refresh = '''  const refreshKey = useCallback(async () => {
    if (role !== 'client' || !layout || !runtime) return
    const key = makeConnectionKey(layout, runtime)
    setConnectionKey(key)
    setMessage(key ? '' : '正在准备公网连接，请稍候…')
  }, [role, layout, runtime])
'''
    new_refresh = '''  const refreshKey = useCallback(async () => {
    if (role !== 'client' || !layout || !runtime) return false
    try {
      const network = await invoke<WanConnectionInfo>('wan_connection_info')
      const key = makeConnectionKey(layout, runtime, network)
      setConnectionKey(key)
      setMessage(
        key
          ? ''
          : '公网中继正在建立，连接密钥暂不可用。请保持网络连接，软件会自动重试。',
      )
      return Boolean(key)
    } catch (error) {
      setConnectionKey('')
      setMessage(`公网连接初始化失败：${String(error)}`)
      return false
    }
  }, [role, layout, runtime])
'''
    text = replace_once(text, old_refresh, new_refresh, "refresh key from live WAN address info")

    text = replace_once(
        text,
        '''  useEffect(() => {
    void refreshKey()
  }, [refreshKey])
''',
        '''  useEffect(() => {
    if (role !== 'client') return
    let cancelled = false
    let timer: number | undefined

    const poll = async () => {
      const ready = await refreshKey()
      if (!cancelled && !ready) {
        timer = window.setTimeout(() => void poll(), 1200)
      }
    }
    void poll()

    return () => {
      cancelled = true
      if (timer !== undefined) window.clearTimeout(timer)
    }
  }, [refreshKey, role])
''',
        "poll WAN readiness until key is valid",
    )

    copy_block = '''  async function copyKey() {
    if (!connectionKey) return
    try {
      await navigator.clipboard.writeText(connectionKey)
    } catch {
      await invoke('write_clipboard_text', { text: connectionKey })
    }
    setCopied(true)
    window.setTimeout(() => setCopied(false), 1600)
  }
'''
    copy_replacement = copy_block + '''
  async function regenerateConnectionKey() {
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
    text = replace_once(text, copy_block, copy_replacement, "real connection key regeneration")

    text = replace_once(
        text,
        '''      await invoke('probe_wan_peer', { endpointId: payload.endpointId })''',
        '''      await invoke('probe_wan_peer', {
        endpointId: payload.endpointId,
        relayUrls: payload.relayUrls,
        directAddresses: payload.directAddresses,
      })''',
        "probe with explicit WAN addresses",
    )

    text = replace_once(
        text,
        '''                <button className="button secondary" onClick={() => void refreshKey()}>刷新密钥显示</button>''',
        '''                <button className="button secondary" disabled={busy} onClick={() => void regenerateConnectionKey()}>重新生成连接密钥</button>''',
        "regenerate key button",
    )

    text = text.replace(
        '<span className="status-dot online" />',
        '<span className={`status-dot ${online ? "online" : ""}`} />',
        1,
    )

    path.write_text(text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()

    patch_transport(root)
    patch_input_targets(root)
    patch_backend_commands(root)
    patch_frontend(root)

    print("WAN reliability overlay applied")


if __name__ == "__main__":
    main()
