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

    text = replace_once(
        text,
        '''#[derive(Clone, Debug)]
pub struct PeerEndpoint {
    pub addr: String,
    pub public_key: String,
    pub protocol_version: u16,
}
''',
        '''#[derive(Clone, Debug)]
pub struct PeerEndpoint {
    pub addr: String,
    pub public_key: String,
    pub protocol_version: u16,
}

#[derive(Clone, Debug, Default, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct WanConnectionInfo {
    pub endpoint_id: String,
    pub relay_urls: Vec<String>,
    pub direct_addresses: Vec<String>,
    pub ready: bool,
}
''',
        "WAN connection info model",
    )

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
        "TransportHandle connection info",
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
        "connection_info getter",
    )

    text = replace_once(
        text,
        '''pub fn validate_endpoint_id(value: &str) -> Result<(), String> {
    EndpointId::from_z32(value.trim())
        .map(|_| ())
        .map_err(|error| format!("invalid WAN endpoint id: {error}"))
}
''',
        '''pub fn validate_endpoint_id(value: &str) -> Result<(), String> {
    EndpointId::from_z32(value.trim())
        .map(|_| ())
        .map_err(|error| format!("invalid WAN endpoint id: {error}"))
}

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
''',
        "explicit EndpointAddr parser",
    )

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
        "transport shared WAN info",
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
        "run_transport WAN info argument",
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
        "TransportHandle WAN info init",
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
        "run_transport signature WAN info",
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
        "continuous WAN address refresh",
    )

    text = replace_once(
        text,
        '''async fn send_datagram_now(
    endpoint: &Endpoint,''',
        '''fn current_connection_info(endpoint: &Endpoint) -> WanConnectionInfo {
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
    endpoint: &Endpoint,''',
        "WAN connection info helpers",
    )

    text = replace_once(
        text,
        '''    let endpoint_id = EndpointId::from_z32(peer.public_key.trim())
        .map_err(|error| format!("invalid WAN endpoint id: {error}"))?;
    let key = endpoint_id.to_z32();''',
        '''    let endpoint_addr = endpoint_addr_for_peer(peer)?;
    let key = endpoint_addr.id.to_z32();''',
        "ensure_connection EndpointAddr",
    )

    text = replace_once(
        text,
        '''    let connection = tokio::time::timeout(CONNECT_TIMEOUT, endpoint.connect(endpoint_id, ALPN))
        .await
        .map_err(|_| format!("WAN connect to {key} timed out"))?
        .map_err(|error| format!("WAN connect to {key} failed: {error}"))?;''',
        '''    let connection = tokio::time::timeout(CONNECT_TIMEOUT, endpoint.connect(endpoint_addr, ALPN))
        .await
        .map_err(|_| format!("连接目标电脑超时，请确认对方软件保持运行并重新生成连接密钥。"))?
        .map_err(|error| {
            let detail = error.to_string();
            if detail.contains("No addressing information available") {
                "目标电脑没有可用的公网地址信息。请在被控电脑保持软件运行，等待显示“连接服务正常”后点击“重新生成连接密钥”，再用新密钥连接。".to_string()
            } else {
                format!("WAN connect to {key} failed: {detail}")
            }
        })?;''',
        "connect using explicit EndpointAddr",
    )

    path.write_text(text, encoding="utf-8")


def patch_device_schema(root: Path) -> None:
    rust_path = root / "src-tauri" / "src" / "lib.rs"
    rust = rust_path.read_text(encoding="utf-8")
    rust = replace_once(
        rust,
        '''    #[serde(default)]
    transport_public_key: String,
    #[serde(default = "default_protocol_version")]''',
        '''    #[serde(default)]
    transport_public_key: String,
    #[serde(default)]
    wan_cluster_id: String,
    #[serde(default)]
    wan_pair_secret: String,
    #[serde(default)]
    wan_relay_urls: Vec<String>,
    #[serde(default)]
    wan_direct_addresses: Vec<String>,
    #[serde(default = "default_protocol_version")]''',
        "Rust Device WAN persistence fields",
    )
    rust_path.write_text(rust, encoding="utf-8")

    types_path = root / "src" / "types.ts"
    types = types_path.read_text(encoding="utf-8")
    types = replace_once(
        types,
        '''  transportPublicKey: string
  protocolVersion: number''',
        '''  transportPublicKey: string
  wanClusterId?: string
  wanPairSecret?: string
  wanRelayUrls?: string[]
  wanDirectAddresses?: string[]
  protocolVersion: number''',
        "TypeScript Device WAN persistence fields",
    )
    types_path.write_text(types, encoding="utf-8")


def patch_input_targets(root: Path) -> None:
    path = root / "src-tauri" / "src" / "input.rs"
    text = path.read_text(encoding="utf-8")

    text = replace_once(
        text,
        '''fn wan_target_credentials(device: &Device) -> Option<(String, String, String)> {
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
''',
        '''fn wan_target_credentials(device: &Device) -> Option<(String, String, String)> {
    if device.source != "wan-key" {
        return None;
    }
    let endpoint_id = device.transport_public_key.trim();
    if !endpoint_id.is_empty()
        && !device.wan_cluster_id.trim().is_empty()
        && !device.wan_pair_secret.trim().is_empty()
    {
        return Some((
            endpoint_id.to_string(),
            device.wan_cluster_id.trim().to_string(),
            device.wan_pair_secret.trim().to_string(),
        ));
    }

    // Legacy alpha.4 compatibility: recover credentials from the old host field.
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

fn wan_target_addr(device: &Device, endpoint_id: &str) -> String {
    quic_transport::format_wan_peer_addr(
        endpoint_id,
        &device.wan_relay_urls,
        &device.wan_direct_addresses,
    )
}
''',
        "persisted WAN target credentials",
    )

    text = replace_once(
        text,
        '''        let target_addr = wan_credentials
            .as_ref()
            .map(|(endpoint_id, _, _)| format!("wan:{endpoint_id}"))
            .unwrap_or_else(|| format!("{}:{}", device.host, quic_port));''',
        '''        let target_addr = wan_credentials
            .as_ref()
            .map(|(endpoint_id, _, _)| wan_target_addr(device, endpoint_id))
            .unwrap_or_else(|| format!("{}:{}", device.host, quic_port));''',
        "input target explicit WAN address",
    )

    path.write_text(text, encoding="utf-8")


def patch_backend_commands(root: Path) -> None:
    path = root / "src-tauri" / "src" / "lib.rs"
    text = path.read_text(encoding="utf-8")

    text = replace_once(
        text,
        '''#[tauri::command]
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
''',
        '''#[tauri::command]
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
        return Err("连接密钥没有携带可用地址。请在被控电脑升级到当前版本并重新生成连接密钥。".to_string());
    }
    let transport = state
        .quic_transport_handle()
        .ok_or_else(|| "公网连接服务还没有启动，请稍后重试。".to_string())?;
    let addr = quic_transport::format_wan_peer_addr(
        endpoint_id.trim(),
        &relay_urls,
        &direct_addresses,
    );
    let peer = transport.peer(
        addr,
        endpoint_id.trim().to_string(),
        quic_transport::PROTOCOL_VERSION,
    );
    transport.probe(peer)
}
''',
        "WAN connection-info and robust probe commands",
    )

    text = replace_once(
        text,
        '''            scan_lan_peers,
            probe_wan_peer,
            probe_lan_peer,''',
        '''            scan_lan_peers,
            wan_connection_info,
            probe_wan_peer,
            probe_lan_peer,''',
        "register WAN connection-info command",
    )

    path.write_text(text, encoding="utf-8")


def patch_frontend(root: Path) -> None:
    path = root / "src" / "App.tsx"
    text = path.read_text(encoding="utf-8")

    text = replace_once(
        text,
        '''interface ConnectionKeyPayload {
  version: 1
  endpointId: string
  name: string
  platform: string
  clusterId: string
  pairSecret: string
  screens: Screen[]
}
''',
        '''interface ConnectionKeyPayload {
  version: 2
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
''',
        "connection key v2 model",
    )

    text = replace_once(
        text,
        '''function remoteDevices(layout?: LayoutState) {''',
        '''function randomHex(byteCount: number) {
  const bytes = new Uint8Array(byteCount)
  crypto.getRandomValues(bytes)
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('')
}

function remoteDevices(layout?: LayoutState) {''',
        "secure key rotation helper",
    )

    text = replace_once(
        text,
        '''function makeConnectionKey(layout: LayoutState, runtime: RuntimeStatus) {
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
}''',
        '''function makeConnectionKey(layout: LayoutState, runtime: RuntimeStatus, network: WanConnectionInfo) {
  const local = localDevice(layout)
  const endpointId = network.endpointId.trim() || runtime.discovery.localPeer.transportPublicKey.trim()
  const relayUrls = network.relayUrls.filter((value) => value.trim())
  const directAddresses = network.directAddresses.filter((value) => value.trim())
  if (
    !local ||
    !endpointId ||
    !network.ready ||
    relayUrls.length === 0 ||
    !layout.clusterId.trim() ||
    !layout.pairSecret.trim()
  ) return ''
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
}''',
        "make connection key only after relay-ready",
    )

    text = replace_once(
        text,
        '''    parsed.version !== 1 ||
    !parsed.endpointId?.trim() ||
    !parsed.clusterId?.trim() ||
    !parsed.pairSecret?.trim() ||
    !Array.isArray(parsed.screens) ||''',
        '''    parsed.version !== 2 ||
    !parsed.endpointId?.trim() ||
    !parsed.clusterId?.trim() ||
    !parsed.pairSecret?.trim() ||
    !Array.isArray(parsed.relayUrls) ||
    parsed.relayUrls.length === 0 ||
    !Array.isArray(parsed.directAddresses) ||
    !Array.isArray(parsed.screens) ||''',
        "connection key v2 validation",
    )

    text = replace_once(
        text,
        '''  return parsed
}''',
        '''  if (parsed.version !== 2) {
    throw new Error('这是旧版本连接密钥。请在被控电脑升级到当前版本后重新生成连接密钥。')
  }
  return parsed
}''',
        "old key actionable error",
    )

    text = replace_once(
        text,
        '''    transportPublicKey: endpointId,
    protocolVersion: 2,''',
        '''    transportPublicKey: endpointId,
    wanClusterId: payload.clusterId,
    wanPairSecret: payload.pairSecret,
    wanRelayUrls: payload.relayUrls,
    wanDirectAddresses: payload.directAddresses,
    protocolVersion: 2,''',
        "persist WAN key route fields",
    )

    text = replace_once(
        text,
        '''  const online = Boolean(runtime?.started && runtime.discovery.localPeer.transportPublicKey)

  const refreshKey = useCallback(async () => {
    if (role !== 'client' || !layout || !runtime) return
    const key = makeConnectionKey(layout, runtime)
    setConnectionKey(key)
    setMessage(key ? '' : '正在准备公网连接，请稍候…')
  }, [role, layout, runtime])''',
        '''  const online = role === 'client'
    ? Boolean(runtime?.started && connectionKey)
    : Boolean(runtime?.started && runtime.discovery.localPeer.transportPublicKey)

  const refreshKey = useCallback(async () => {
    if (role !== 'client' || !layout || !runtime) return false
    try {
      const network = await invoke<WanConnectionInfo>('wan_connection_info')
      const key = makeConnectionKey(layout, runtime, network)
      setConnectionKey(key)
      setMessage(key ? '' : '正在注册公网连接地址，请保持网络正常，稍后会自动生成密钥…')
      return Boolean(key)
    } catch (error) {
      setConnectionKey('')
      setMessage(`公网连接服务未就绪：${String(error)}`)
      return false
    }
  }, [role, layout, runtime])''',
        "live WAN-ready key refresh",
    )

    text = replace_once(
        text,
        '''  useEffect(() => {
    void refreshKey()
  }, [refreshKey])''',
        '''  useEffect(() => {
    if (role !== 'client') return
    let stopped = false
    let timer: number | undefined
    const poll = async () => {
      const ready = await refreshKey()
      if (!stopped && !ready) timer = window.setTimeout(() => void poll(), 1200)
    }
    void poll()
    return () => {
      stopped = true
      if (timer !== undefined) window.clearTimeout(timer)
    }
  }, [role, refreshKey])''',
        "automatic relay-ready polling",
    )

    text = replace_once(
        text,
        '''  async function copyKey() {
    if (!connectionKey) return''',
        '''  async function regenerateConnectionKey() {
    if (role !== 'client' || !layout || !runtime) return
    setBusy(true)
    setConnectionKey('')
    setCopied(false)
    setMessage('正在撤销旧密钥并生成新的连接授权…')
    try {
      const state = await saveLayout({ ...layout, pairSecret: randomHex(32) })
      setSnapshot(state)
      setRuntime(state.runtime)
      const network = await invoke<WanConnectionInfo>('wan_connection_info')
      const key = makeConnectionKey(state.layout, state.runtime, network)
      setConnectionKey(key)
      setMessage(key ? '新的连接密钥已生成，旧密钥已失效。' : '新的授权已生成，正在等待公网地址就绪…')
    } catch (error) {
      setMessage(`重新生成连接密钥失败：${String(error)}`)
    } finally {
      setBusy(false)
    }
  }

  async function copyKey() {
    if (!connectionKey) return''',
        "real key regeneration action",
    )

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
        '''                <button className="button secondary" disabled={busy} onClick={() => void regenerateConnectionKey()}>{busy ? '正在生成…' : '重新生成连接密钥'}</button>''',
        "key regeneration button",
    )

    path.write_text(text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    patch_transport(root)
    patch_device_schema(root)
    patch_input_targets(root)
    patch_backend_commands(root)
    patch_frontend(root)
    print("WAN reliability overlay applied")


if __name__ == "__main__":
    main()
