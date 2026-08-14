# 视饭AI：主机共享 v1 Native Architecture

v1 is a clean break from the v0.x Python + Deskflow wrapper architecture.

## Why this exists

The v0.x line wrapped a separately configured Deskflow process and depended on TCP 24800 readiness/configuration. That added several layers whose state could disagree: Python UI, bridge/listener, Windows firewall rules, Deskflow settings, Deskflow protocol handshake and remote network state.

v1 removes that stack instead of adding more compatibility probes.

## Foundation

The initial v1 implementation is based on the MIT-licensed MyKVM Rust/Tauri architecture, pinned to upstream commit `a2ea4164861de31b562c8417eeb7879dbc8c23cb`, then branded and adapted for 视饭AI.

We selected this foundation because the native core already implements the pieces required by this product:

- Rust native core on Windows and macOS
- Windows native keyboard/mouse hooks and injection
- macOS CoreGraphics input capture/injection and permission handling
- UDP LAN discovery
- QUIC transport encrypted with TLS 1.3
- QUIC datagrams for low-latency input
- reliable QUIC streams for clipboard/file payloads
- screen topology and edge crossing
- reconnect/runtime state management
- Windows elevated input helper support
- Tauri installers for Windows and macOS

The original upstream source remains MIT licensed and attribution is retained in `THIRD_PARTY_NOTICES.md`.

## v1 network model

Default network transport:

- UDP 47833: local peer discovery/probing
- UDP 47834: QUIC/TLS 1.3 input + clipboard transport

There is no Deskflow process, no TCP 24800 listener and no Python TCP forwarding layer.

The transport uses the peer certificate/public key advertised during discovery and pins the peer for encrypted QUIC communication. The product is still explicitly intended for trusted LAN use.

## Pairing model

The upstream pairing path already supports an explicit pairing challenge, persistent cluster credentials, paired-controller ACLs and credential validation before accepting input.

For the first v1 alpha we keep the proven challenge/confirm flow but change the human code to the product format `XXXX-XXXX-XXXX`. This is intentionally narrower than redesigning transport and pairing simultaneously. After the two-machine native transport has passed real-device testing, the UX can be inverted to the final product requirement: host displays a persistent key and the secondary enters it without an IP address.

## Packaging

Windows:

- Tauri/NSIS installer
- custom product icon
- bundled elevated input helper
- Windows firewall configuration from the native upstream implementation

macOS:

- native `.app` + `.dmg`
- minimum macOS 12
- Apple Silicon and Intel builds
- first run still requires Accessibility/Input Monitoring permission

## Release gates

A v1 build is not called stable merely because CI compiled it. The release pipeline verifies source build and packaging. Real-device acceptance still requires:

1. Windows 11 -> Windows 11 mouse crossing and keyboard following
2. Windows -> macOS
3. macOS -> Windows
4. clipboard text in both directions
5. stop/start and reconnect without stale UI states
6. 30-minute soak before beta, 12-hour soak before stable

The old v0.x implementation is retained only as legacy history while v1 is validated.
