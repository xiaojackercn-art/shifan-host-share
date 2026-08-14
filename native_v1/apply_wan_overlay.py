#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    overlay_dir = Path(__file__).resolve().parent

    shutil.copy2(overlay_dir / "product_app.tsx", root / "src" / "App.tsx")
    shutil.copy2(overlay_dir / "product_index.css", root / "src" / "index.css")
    shutil.copy2(overlay_dir / "quic_transport_iroh.rs", root / "src-tauri" / "src" / "quic_transport.rs")

    # Frontend type accepts the WAN device source returned/persisted by the product UI.
    types_path = root / "src" / "types.ts"
    types = types_path.read_text(encoding="utf-8")
    types = replace_once(
        types,
        "source?: 'detected' | 'manual'",
        "source?: 'detected' | 'manual' | 'wan-key'",
        "frontend Device.source",
    )
    types_path.write_text(types, encoding="utf-8")

    # Iroh gives this product globally dialable EndpointIds, NAT traversal and relay fallback.
    # Disable Iroh's optional default portmapper feature on desktop builds. Keep the ring TLS
    # backend explicitly enabled.
    cargo_path = root / "src-tauri" / "Cargo.toml"
    cargo = cargo_path.read_text(encoding="utf-8")
    iroh_dep = 'iroh = { version = "1.0.3", default-features = false, features = ["tls-ring"] }'
    if iroh_dep not in cargo:
        cargo = replace_once(cargo, 'quinn = "0.11"', f'quinn = "0.11"\n{iroh_dep}', "Cargo iroh dependency")

    # netwatch -> wmi 0.18.x accepts a wide windows/windows-core range. On a fresh Windows
    # resolver this can otherwise select windows 0.61 with windows-core 0.62, which are
    # different COM type universes and cannot compile together. Force wmi's compatible branch
    # to the matching Windows 0.61 family while allowing unrelated dependencies to keep their
    # own 0.62 family when required.
    win_anchor = 'windows-service = "0.8.1"'
    win_pin = 'windows-service = "0.8.1"\nwindows = "=0.61.3"\nwindows-core = "=0.61.2"\nwindows-result = "=0.3.4"'
    if 'windows-core = "=0.61.2"' not in cargo:
        cargo = replace_once(cargo, win_anchor, win_pin, "Windows COM dependency pins")
    cargo_path.write_text(cargo, encoding="utf-8")

    # Explicitly use the generated product icon for the application bundle and NSIS installer.
    conf_path = root / "src-tauri" / "tauri.conf.json"
    conf = json.loads(conf_path.read_text(encoding="utf-8"))
    bundle = conf.setdefault("bundle", {})
    bundle["icon"] = [
        "icons/32x32.png",
        "icons/128x128.png",
        "icons/128x128@2x.png",
        "icons/icon.icns",
        "icons/icon.ico",
    ]
    windows = bundle.setdefault("windows", {})
    nsis = windows.setdefault("nsis", {})
    nsis["installerIcon"] = "icons/icon.ico"
    nsis["uninstallerIcon"] = "icons/icon.ico"
    conf_path.write_text(json.dumps(conf, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # WAN-aware input target credentials and capability authorization.
    input_path = root / "src-tauri" / "src" / "input.rs"
    input_rs = input_path.read_text(encoding="utf-8")

    input_rs = replace_once(
        input_rs,
        '''fn build_input_targets(layout: &LayoutState, native_layout: &LayoutState) -> Vec<InputTarget> {''',
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

fn build_input_targets(layout: &LayoutState, native_layout: &LayoutState) -> Vec<InputTarget> {''',
        "insert WAN target credential parser",
    )

    input_rs = replace_once(
        input_rs,
        '''    }) {
        let quic_port = normalize_quic_port(device.transport_port, device.quic_port);
        for layout_local_screen in local_screens {''',
        '''    }) {
        let quic_port = normalize_quic_port(device.transport_port, device.quic_port);
        let wan_credentials = wan_target_credentials(device);
        let target_cluster_id = wan_credentials
            .as_ref()
            .map(|(_, cluster_id, _)| cluster_id.clone())
            .unwrap_or_else(|| layout.cluster_id.clone());
        let target_pair_secret = wan_credentials
            .as_ref()
            .map(|(_, _, pair_secret)| pair_secret.clone())
            .unwrap_or_else(|| layout.pair_secret.clone());
        let target_addr = wan_credentials
            .as_ref()
            .map(|(endpoint_id, _, _)| format!("wan:{endpoint_id}"))
            .unwrap_or_else(|| format!("{}:{}", device.host, quic_port));
        for layout_local_screen in local_screens {''',
        "WAN target fields",
    )

    input_rs = replace_once(
        input_rs,
        '''                        cluster_id: layout.cluster_id.clone(),
                        pair_secret: layout.pair_secret.clone(),
                        target_addr: format!("{}:{}", device.host, quic_port),''',
        '''                        cluster_id: target_cluster_id.clone(),
                        pair_secret: target_pair_secret.clone(),
                        target_addr: target_addr.clone(),''',
        "WAN target credential assignment",
    )

    input_rs = replace_once(
        input_rs,
        '''    InputPacketContext {
        origin_device_id,
        cluster_id: layout.cluster_id.clone(),
        pair_secret: layout.pair_secret.clone(),
        peer,
        event,
    }''',
        '''    InputPacketContext {
        origin_device_id,
        cluster_id: target.cluster_id.clone(),
        pair_secret: target.pair_secret.clone(),
        peer,
        event,
    }''',
        "key-event WAN credentials",
    )

    input_rs = replace_once(
        input_rs,
        '''    if !device.online {
        return;
    }

    device.online = false;''',
        '''    if !device.online || device.source == "wan-key" {
        return;
    }

    device.online = false;''',
        "keep WAN target retryable",
    )

    input_rs = replace_once(
        input_rs,
        '''    if cluster_id != layout.cluster_id || pair_secret != layout.pair_secret {
        return false;
    }

    if layout.paired_controllers.iter().any(|controller| {''',
        '''    if cluster_id != layout.cluster_id || pair_secret != layout.pair_secret {
        return false;
    }

    // The WAN connection key is a capability: possession of the embedded
    // cluster id + pair secret authorizes control. The transport is separately
    // authenticated by the Iroh EndpointId in the key.
    if layout.machine_role == "client" {
        return true;
    }

    if layout.paired_controllers.iter().any(|controller| {''',
        "WAN capability authorization",
    )

    input_rs = replace_once(
        input_rs,
        '''    layout
        .devices
        .iter()
        .any(|device| device.role == "local" && device.id == target_device_id)
}''',
        '''    layout.devices.iter().any(|device| {
        device.role == "local"
            && (device.id == target_device_id
                || (!device.transport_public_key.trim().is_empty()
                    && device.transport_public_key == target_device_id))
    })
}''',
        "target local EndpointId acceptance",
    )

    input_path.write_text(input_rs, encoding="utf-8")

    # Product backend: probe a global endpoint before persisting a key connection,
    # and keep WAN-key devices online instead of LAN discovery marking them offline.
    lib_path = root / "src-tauri" / "src" / "lib.rs"
    lib_rs = lib_path.read_text(encoding="utf-8")

    lib_rs = replace_once(
        lib_rs,
        '''#[tauri::command]
fn probe_lan_peer(host: String, state: tauri::State<'_, AppRuntime>) -> Result<LanPeer, String> {''',
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

#[tauri::command]
fn probe_lan_peer(host: String, state: tauri::State<'_, AppRuntime>) -> Result<LanPeer, String> {''',
        "insert WAN probe command",
    )

    lib_rs = replace_once(
        lib_rs,
        '''            scan_lan_peers,
            probe_lan_peer,''',
        '''            scan_lan_peers,
            probe_wan_peer,
            probe_lan_peer,''',
        "register WAN probe command",
    )

    lib_rs = replace_once(
        lib_rs,
        '''        let peer = peers
            .iter()
            .find(|peer| device_matches_peer(device, peer, &cluster_id));''',
        '''        if device.source == "wan-key" {
            device.online = true;
            device.input_ready = true;
            device.protocol_version = quic_transport::PROTOCOL_VERSION;
            continue;
        }

        let peer = peers
            .iter()
            .find(|peer| device_matches_peer(device, peer, &cluster_id));''',
        "keep WAN-key devices out of LAN presence",
    )

    # Runtime and shell branding; these also cover title bar fallback and tray text.
    lib_rs = lib_rs.replace('.title("MyKVM")', '.title("视饭AI:主机共享")')
    lib_rs = lib_rs.replace('"Show mykvm"', '"显示 视饭AI:主机共享"')
    lib_rs = lib_rs.replace('"mykvm · 已启动"', '"视饭AI:主机共享 · 已启动"')
    lib_rs = lib_rs.replace('"mykvm · 已停止"', '"视饭AI:主机共享 · 已停止"')
    lib_path.write_text(lib_rs, encoding="utf-8")

    print("WAN key product overlay applied")


if __name__ == "__main__":
    main()
