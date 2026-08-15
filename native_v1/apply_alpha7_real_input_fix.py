#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def require_replace(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def require_regex(text: str, pattern: str, repl: str, label: str, flags: int = 0) -> str:
    updated, count = re.subn(pattern, repl, text, count=1, flags=flags)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return updated


def patch_input(root: Path) -> None:
    path = root / "src-tauri" / "src" / "input.rs"
    text = path.read_text(encoding="utf-8")

    # Control transitions must never depend on a short-lived source-address auth cache.
    # Every keyboard/button/wheel packet carries complete credentials. Only mouse motion,
    # which is high-frequency replaceable state, may use the cached authorization shortcut.
    text = require_replace(
        text,
        "    let include_credentials = should_send_full_input_credentials(&peer.addr);",
        "    let include_credentials = !low_latency_mouse || should_send_full_input_credentials(&peer.addr);",
        "full credentials for keyboard/button/wheel",
    )

    # Alpha 7 is explicitly a 1000 Hz capture target. The transport still coalesces motion,
    # so this does not build an old-coordinate backlog when a path is temporarily slower.
    if "const MOUSE_MOVE_SEND_INTERVAL_MS: u64 = 1;" not in text:
        text = require_regex(
            text,
            r"const MOUSE_MOVE_SEND_INTERVAL_MS: u64 = \d+;\nconst DRAG_MOVE_SEND_INTERVAL_MS: u64 = \d+;",
            "const MOUSE_MOVE_SEND_INTERVAL_MS: u64 = 1;\nconst DRAG_MOVE_SEND_INTERVAL_MS: u64 = 1;",
            "1000 Hz pointer cadence",
        )

    path.write_text(text, encoding="utf-8")


def patch_transport(root: Path) -> None:
    path = root / "src-tauri" / "src" / "quic_transport.rs"
    text = path.read_text(encoding="utf-8")

    # Share the already-established QUIC connections with TransportHandle. Once probe/connect
    # has completed, interactive datagrams can be written directly to the live QUIC connection
    # from the capture thread instead of taking an extra application-level Tokio queue hop.
    text = require_replace(
        text,
        "    connection_info: Arc<Mutex<WanConnectionInfo>>,\n    peer_health: HealthMap,",
        "    connection_info: Arc<Mutex<WanConnectionInfo>>,\n    connections: ConnectionMap,\n    peer_health: HealthMap,",
        "TransportHandle shared live connections",
    )

    getter_anchor = '''    pub fn peer(&self, addr: String, public_key: String, protocol_version: u16) -> PeerEndpoint {
        PeerEndpoint {
            addr,
            public_key,
            protocol_version,
        }
    }
'''
    getter_replacement = getter_anchor + '''
    fn try_fast_datagram(&self, peer: &PeerEndpoint, payload: &[u8]) -> bool {
        let Ok(endpoint_id) = EndpointId::from_z32(peer.public_key.trim()) else {
            return false;
        };
        let key = endpoint_id.to_z32();
        let connection = self
            .connections
            .lock()
            .ok()
            .and_then(|connections| connections.get(&key).cloned())
            .filter(|connection| connection.close_reason().is_none());
        let Some(connection) = connection else {
            return false;
        };

        match connection.send_datagram(payload.to_vec().into()) {
            Ok(()) => {
                record_peer_success(&self.peer_health, &key);
                true
            }
            Err(error) => {
                // QUIC can transiently apply backpressure. Preserve reliability by falling
                // back to the normal scheduler rather than dropping a control transition.
                log::debug!("realtime fast path to {key} fell back to scheduler: {error}");
                false
            }
        }
    }
'''
    text = require_replace(text, getter_anchor, getter_replacement, "live QUIC fast-path helper")

    text = require_replace(
        text,
        '''    pub fn send_datagram(&self, peer: PeerEndpoint, payload: Vec<u8>) -> Result<(), String> {
        self.validate_datagram(&peer, &payload)?;
        self.commands''',
        '''    pub fn send_datagram(&self, peer: PeerEndpoint, payload: Vec<u8>) -> Result<(), String> {
        self.validate_datagram(&peer, &payload)?;
        if self.try_fast_datagram(&peer, &payload) {
            return Ok(());
        }
        self.commands''',
        "control datagram direct fast path",
    )

    text = require_replace(
        text,
        '''        let key = self.validate_datagram(&peer, &payload)?;
        let should_schedule = {''',
        '''        let key = self.validate_datagram(&peer, &payload)?;
        if self.try_fast_datagram(&peer, &payload) {
            return Ok(());
        }
        let should_schedule = {''',
        "mouse datagram direct fast path",
    )

    text = require_replace(
        text,
        '''    let connection_info = Arc::new(Mutex::new(WanConnectionInfo::default()));
    let loop_health = Arc::clone(&peer_health);
    let loop_latest = Arc::clone(&latest_datagrams);
    let loop_connection_info = Arc::clone(&connection_info);''',
        '''    let connection_info = Arc::new(Mutex::new(WanConnectionInfo::default()));
    let connections: ConnectionMap = Arc::new(Mutex::new(HashMap::new()));
    let loop_health = Arc::clone(&peer_health);
    let loop_latest = Arc::clone(&latest_datagrams);
    let loop_connection_info = Arc::clone(&connection_info);
    let loop_connections = Arc::clone(&connections);''',
        "create shared live connection map",
    )

    # Alpha 6 fairness overlay passes loop_command_tx immediately after command_rx.
    text = require_replace(
        text,
        '''                command_rx,
                loop_command_tx,
                on_datagram,''',
        '''                command_rx,
                loop_command_tx,
                loop_connections,
                on_datagram,''',
        "pass live connection map to transport loop",
    )

    text = require_replace(
        text,
        '''        public_key: ready.public_key,
        connection_info,
        peer_health,''',
        '''        public_key: ready.public_key,
        connection_info,
        connections,
        peer_health,''',
        "store live connection map in handle",
    )

    text = require_replace(
        text,
        '''    mut commands: tokio_mpsc::UnboundedReceiver<TransportCommand>,
    command_tx: tokio_mpsc::UnboundedSender<TransportCommand>,
    on_datagram: DatagramHandler,''',
        '''    mut commands: tokio_mpsc::UnboundedReceiver<TransportCommand>,
    command_tx: tokio_mpsc::UnboundedSender<TransportCommand>,
    connections: ConnectionMap,
    on_datagram: DatagramHandler,''',
        "transport loop live connection argument",
    )

    text = require_replace(
        text,
        '''    let connections: ConnectionMap = Arc::new(Mutex::new(HashMap::new()));
    let mut address_refresh = tokio::time::interval(Duration::from_secs(1));''',
        '''    let mut address_refresh = tokio::time::interval(Duration::from_secs(1));''',
        "remove transport-local connection map",
    )

    path.write_text(text, encoding="utf-8")


def patch_backend_key_rotation(root: Path) -> None:
    path = root / "src-tauri" / "src" / "lib.rs"
    text = path.read_text(encoding="utf-8")

    text = require_replace(
        text,
        '''        // pair_secret is backend-owned and intentionally ignored by save_layout.
        // Rotate it here so the operation is real and atomic instead of a UI-only refresh.
        layout.pair_secret = default_pair_secret();
        layout.paired_controllers.clear();''',
        '''        // Rotate BOTH capability components. This makes the visible connection key
        // cryptographically and structurally different on every successful rotation and
        // guarantees every previously copied capability is revoked.
        let previous_cluster = layout.cluster_id.clone();
        let previous_secret = layout.pair_secret.clone();
        let mut next_cluster = default_cluster_id();
        let mut next_secret = default_pair_secret();
        while next_cluster == previous_cluster {
            next_cluster = default_cluster_id();
        }
        while next_secret == previous_secret {
            next_secret = default_pair_secret();
        }
        layout.cluster_id = next_cluster;
        layout.pair_secret = next_secret;
        layout.paired_controllers.clear();''',
        "strong backend key rotation",
    )

    path.write_text(text, encoding="utf-8")


def patch_frontend(root: Path) -> None:
    path = root / "src" / "App.tsx"
    text = path.read_text(encoding="utf-8")

    text = require_replace(
        text,
        '''            <strong>{PRODUCT}</strong>
            <span>跨设备键鼠控制</span>''',
        '''            <strong>{PRODUCT}</strong>
            <span>跨设备键鼠控制 · v{APP_VERSION}</span>''',
        "visible running version",
    )

    # The backend is the source of truth. A successful UI result now requires both backend-owned
    # capability components to have changed, not merely a changed textarea string.
    text = require_replace(
        text,
        '''      const previousKey = connectionKey
      const state = await invoke<AppStateSnapshot>('regenerate_wan_connection_key')''',
        '''      const previousKey = connectionKey
      const previousCluster = snapshot?.layout.clusterId ?? ''
      const previousSecret = snapshot?.layout.pairSecret ?? ''
      const state = await invoke<AppStateSnapshot>('regenerate_wan_connection_key')
      if (
        !state.layout.clusterId ||
        !state.layout.pairSecret ||
        state.layout.clusterId === previousCluster ||
        state.layout.pairSecret === previousSecret
      ) {
        throw new Error('后端连接授权没有完成轮换，已拒绝显示成功状态。')
      }''',
        "frontend verifies backend capability rotation",
    )

    # Explicit button types avoid any WebView/form default-submit behavior if markup is wrapped
    # by the shell in a future Tauri/WebView version.
    text = text.replace(
        '<button className="button primary" disabled={!connectionKey} onClick={() => void copyKey()}>',
        '<button type="button" className="button primary" disabled={busy || !connectionKey} onClick={() => void copyKey()}>',
        1,
    )
    text = text.replace(
        '<button className="button secondary" disabled={busy} onClick={() => void regenerateConnectionKey()}>',
        '<button type="button" className="button secondary" disabled={busy} onClick={() => void regenerateConnectionKey()}>',
        1,
    )

    # Windows can move the cursor through SetCursorPos even when UIPI rejects keyboard/click
    # SendInput. A controlled Windows machine therefore runs elevated so all ordinary desktop
    # apps receive the same keyboard/mouse input integrity level.
    text = require_replace(
        text,
        '''          const next = await startRuntime()
          if (alive) setRuntime(next)''',
        '''          const next = await startRuntime()
          if (alive) setRuntime(next)
          const controlledLocal = localDevice(state.layout)
          if (
            alive &&
            state.layout.machineRole === 'client' &&
            controlledLocal?.platform === 'windows' &&
            next.privilege.canElevate &&
            !next.privilege.isElevated
          ) {
            setMessage('Windows 被控端正在申请管理员权限，以确保键盘与点击可注入所有普通桌面窗口…')
            await invoke('restart_as_admin')
            return
          }''',
        "auto-elevate existing Windows controlled role",
    )

    text = require_replace(
        text,
        '''      const nextRuntime = await startRuntime()
      setRuntime(nextRuntime)
      setConnectionKey('')''',
        '''      const nextRuntime = await startRuntime()
      setRuntime(nextRuntime)
      setConnectionKey('')
      const nextLocal = localDevice(state.layout)
      if (
        nextRole === 'client' &&
        nextLocal?.platform === 'windows' &&
        nextRuntime.privilege.canElevate &&
        !nextRuntime.privilege.isElevated
      ) {
        setMessage('Windows 被控端需要管理员权限以保证完整键鼠控制，正在请求系统授权…')
        await invoke('restart_as_admin')
        return
      }''',
        "auto-elevate newly selected Windows controlled role",
    )

    path.write_text(text, encoding="utf-8")


def patch_windows_installer(root: Path) -> None:
    hooks_dir = root / "src-tauri" / "windows"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hook_path = hooks_dir / "alpha7-hooks.nsh"
    hook_path.write_text(
        r'''!macro NSIS_HOOK_PREINSTALL
  ; A previous tray-resident build can keep the old executable alive while a new
  ; installer is launched. Kill historical product process names before files are
  ; replaced so launching after install cannot reactivate an older in-memory build.
  nsExec::ExecToLog 'taskkill /F /T /IM "视饭AI主机共享.exe"'
  nsExec::ExecToLog 'taskkill /F /T /IM "shifanai-host-share.exe"'
  nsExec::ExecToLog 'taskkill /F /T /IM "mykvm.exe"'
  Sleep 500
!macroend
''',
        encoding="utf-8",
    )

    conf_path = root / "src-tauri" / "tauri.conf.json"
    conf = json.loads(conf_path.read_text(encoding="utf-8"))
    nsis = conf.setdefault("bundle", {}).setdefault("windows", {}).setdefault("nsis", {})
    nsis["installerHooks"] = "./windows/alpha7-hooks.nsh"
    conf_path.write_text(json.dumps(conf, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()

    patch_input(root)
    patch_transport(root)
    patch_backend_key_rotation(root)
    patch_frontend(root)
    patch_windows_installer(root)
    print("alpha.7 real-device input/key/installer fixes applied")


if __name__ == "__main__":
    main()
