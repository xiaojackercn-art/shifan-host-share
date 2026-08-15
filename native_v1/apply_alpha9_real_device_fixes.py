#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def patch_input(root: Path) -> None:
    path = root / "src-tauri" / "src" / "input.rs"
    text = path.read_text(encoding="utf-8")

    # 500 Hz still makes the Windows hook/worker fight over ActiveTarget far more
    # often than a display can present. 250 Hz keeps worst-case software sampling
    # latency under 4 ms while cutting lock/serialization/network pressure in half.
    text = replace_once(
        text,
        "const MOUSE_MOVE_SEND_INTERVAL_MS: u64 = 2;\nconst DRAG_MOVE_SEND_INTERVAL_MS: u64 = 2;",
        "const MOUSE_MOVE_SEND_INTERVAL_MS: u64 = 4;\nconst DRAG_MOVE_SEND_INTERVAL_MS: u64 = 4;",
        "250Hz latest-only pointer cadence",
    )

    # CRITICAL WAN keyboard bug: mouse packets use the cached, already-normalized
    # WAN route (wan:<endpoint>|r=...|a=...). Key packets consult the live layout
    # for modifier remapping, but the old code rebuilt peer.addr from device.host.
    # A WAN-key device.host is a persistence ticket (wan://endpoint/cluster/secret|...)
    # rather than a transport address, so keyboard packets got a malformed route
    # even though mouse packets to the same target worked. Reuse the exact route
    # that was built/validated with the InputTarget.
    old_peer = '''    let peer = layout
        .devices
        .iter()
        .find(|device| device.id == target.device_id)
        .and_then(|device| {
            (device.online && device.input_ready).then(|| quic_transport::PeerEndpoint {
                addr: format!(
                    "{}:{}",
                    device.host,
                    normalize_quic_port(device.transport_port, device.quic_port)
                ),
                public_key: device.transport_public_key.clone(),
                protocol_version: device.protocol_version,
            })
        });'''
    new_peer = '''    let peer = layout
        .devices
        .iter()
        .find(|device| device.id == target.device_id)
        .and_then(|device| {
            (device.online && device.input_ready).then(|| quic_transport::PeerEndpoint {
                // Never rebuild WAN input addresses from Device.host here.
                // target.target_addr is the normalized route shared by mouse and keyboard.
                addr: target.target_addr.clone(),
                public_key: target.transport_public_key.clone(),
                protocol_version: target.protocol_version,
            })
        });'''
    text = replace_once(text, old_peer, new_peer, "keyboard uses normalized WAN target route")

    # Clipboard control had the same persistence-ticket/address mix-up. It does
    # not cause keyboard failure, but leaving it behind would make WAN clipboard
    # traffic reconnect through an invalid address after input starts working.
    old_clipboard_addr = '''        format!(
            "{}:{}",
            device.host,
            normalize_quic_port(device.transport_port, device.quic_port)
        ),'''
    text = replace_once(
        text,
        old_clipboard_addr,
        '''        active.target.target_addr.clone(),''',
        "clipboard reuses normalized WAN target route",
    )

    # The alpha.8 mouse worker consumed its one-slot wake token and then BLOCKED
    # on the same ActiveTarget mutex used by the low-level mouse hook. That could
    # still produce micro-stalls in the hook thread. A missed sample is harmless
    # because motion is latest-state data; never wait for this lock in the worker.
    old_sample = '''                let latest = context
                    .active
                    .lock()
                    .ok()
                    .and_then(|active| active.as_ref().cloned());'''
    new_sample = '''                let latest = context
                    .active
                    .try_lock()
                    .ok()
                    .and_then(|active| active.as_ref().cloned());'''
    text = replace_once(text, old_sample, new_sample, "mouse worker never blocks hook ActiveTarget mutex")

    path.write_text(text, encoding="utf-8")


def patch_transport(root: Path) -> None:
    path = root / "src-tauri" / "src" / "quic_transport.rs"
    text = path.read_text(encoding="utf-8")

    # Give explicit direct candidates enough time to complete NAT traversal before
    # allowing relay fallback. Once this succeeds, the cached connection is a
    # direct-only EndpointAddr connection and realtime input stays off the relay.
    text = replace_once(
        text,
        '''        if let Ok(Ok(connection)) = tokio::time::timeout(
            Duration::from_millis(650),
            endpoint.connect(direct_addr, ALPN),
        )''',
        '''        if let Ok(Ok(connection)) = tokio::time::timeout(
            Duration::from_millis(1800),
            endpoint.connect(direct_addr, ALPN),
        )''',
        "direct path gets a realistic handshake window",
    )

    text = replace_once(
        text,
        '''            return Ok(connection);
        }
    }

    let connection = tokio::time::timeout(CONNECT_TIMEOUT, endpoint.connect(endpoint_addr, ALPN))''',
        '''            return Ok(connection);
        }
        log::info!("WAN peer {key} direct path unavailable after 1800ms; using relay/NAT fallback");
    }

    let connection = tokio::time::timeout(CONNECT_TIMEOUT, endpoint.connect(endpoint_addr, ALPN))''',
        "log explicit relay fallback",
    )

    # Import/probe must not blindly reuse an old cached relay-capable connection.
    # Force one fresh route decision using the just-imported direct candidates;
    # ensure_connection will cache whichever direct-first/fallback path wins.
    old_probe = '''                    TransportCommand::Probe { peer, result } => {
                        let key = health_key(&peer).to_string();
                        let outcome = ensure_connection(&endpoint, &connections, &peer).await.map(|_| ());'''
    new_probe = '''                    TransportCommand::Probe { peer, result } => {
                        let key = health_key(&peer).to_string();
                        if let Ok(mut live) = connections.lock() {
                            live.remove(&key);
                        }
                        log::info!("WAN probe for {key} is forcing a fresh direct-first route decision");
                        let outcome = ensure_connection(&endpoint, &connections, &peer).await.map(|_| ());'''
    text = replace_once(text, old_probe, new_probe, "probe forces fresh direct-first connection selection")

    path.write_text(text, encoding="utf-8")


def patch_frontend(root: Path) -> None:
    path = root / "src" / "App.tsx"
    text = path.read_text(encoding="utf-8")

    # Alpha.8 rotated the backend secret correctly, but base64 JSON keys begin
    # with a long identical prefix (version/endpoint/name/platform), making two
    # genuinely different keys look identical at a glance. Alpha.9 puts a short
    # secret-derived capability id immediately after SFAI2-. Because the backend
    # already guarantees pairSecret changes, the visible key must now change at
    # its very beginning on every successful rotation.
    text = replace_once(
        text,
        "const KEY_PREFIX = 'SFAI1-'",
        "const KEY_PREFIX_V2 = 'SFAI2-'\nconst LEGACY_KEY_PREFIX = 'SFAI1-'",
        "versioned visible connection-key prefix",
    )

    text = replace_once(
        text,
        '''  return KEY_PREFIX + encodeBase64Url(new TextEncoder().encode(JSON.stringify(payload)))''',
        '''  const capabilityId = layout.pairSecret.slice(0, 12).toUpperCase()
  return `${KEY_PREFIX_V2}${capabilityId}-${encodeBase64Url(new TextEncoder().encode(JSON.stringify(payload)))}`''',
        "new keys visibly change after backend rotation",
    )

    old_parse_prefix = '''  const normalized = key.trim()
  if (!normalized.startsWith(KEY_PREFIX)) throw new Error('连接密钥格式不正确。')
  const raw = normalized.slice(KEY_PREFIX.length)
  if (!raw || raw.length > 24000) throw new Error('连接密钥格式不正确。')'''
    new_parse_prefix = '''  const normalized = key.trim()
  let raw = ''
  let capabilityId = ''
  if (normalized.startsWith(KEY_PREFIX_V2)) {
    const body = normalized.slice(KEY_PREFIX_V2.length)
    const separator = body.indexOf('-')
    if (separator <= 0) throw new Error('连接密钥格式不正确。')
    capabilityId = body.slice(0, separator).toUpperCase()
    raw = body.slice(separator + 1)
  } else if (normalized.startsWith(LEGACY_KEY_PREFIX)) {
    // Accept alpha.8 v2 tickets for a non-breaking upgrade. Any key regenerated
    // on alpha.9 is emitted in the visibly-changing SFAI2 format.
    raw = normalized.slice(LEGACY_KEY_PREFIX.length)
  } else {
    throw new Error('连接密钥格式不正确。')
  }
  if (!raw || raw.length > 24000) throw new Error('连接密钥格式不正确。')'''
    text = replace_once(text, old_parse_prefix, new_parse_prefix, "parse SFAI2 plus alpha8 legacy key")

    old_parse_tail = '''  if (
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
  return parsed'''
    new_parse_tail = '''  if (
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
  if (capabilityId && !parsed.pairSecret.toUpperCase().startsWith(capabilityId)) {
    throw new Error('连接密钥校验失败，请在被控电脑重新生成后复制完整密钥。')
  }
  return parsed'''
    text = replace_once(text, old_parse_tail, new_parse_tail, "validate visible capability id")

    # Make the reason for the visible key change explicit next to the existing
    # fingerprint so users can immediately verify rotation without comparing a
    # long base64 ticket character by character.
    old_meta = '''                <span>协议 v2</span>
                <span>{connectionKey ? `指纹 ${keyFingerprint(connectionKey)}` : '等待公网通道'}</span>'''
    new_meta = '''                <span>协议 v2</span>
                <span>{connectionKey ? `密钥编号 ${layout?.pairSecret.slice(0, 12).toUpperCase() ?? ''}` : '等待公网通道'}</span>
                <span>{connectionKey ? `指纹 ${keyFingerprint(connectionKey)}` : '等待公网通道'}</span>'''
    text = replace_once(text, old_meta, new_meta, "show visible rotated capability id")

    path.write_text(text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()

    patch_input(root)
    patch_transport(root)
    patch_frontend(root)
    print("alpha.9 real-device key/keyboard/mouse fixes applied")


if __name__ == "__main__":
    main()
