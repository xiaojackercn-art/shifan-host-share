#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

PRODUCT_TITLE = "视饭AI:主机共享"
PRODUCT_FS_NAME = "视饭AI主机共享"
PACKAGE_NAME = "shifanai-host-share"
IDENTIFIER = "com.csshifan.shifanhostshare"
UPSTREAM_REPO = "https://github.com/XxMinor/mykvm"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def replace_text(path: Path, replacements: list[tuple[str, str]]) -> None:
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    old = text
    for source, target in replacements:
        text = text.replace(source, target)
    if text != old:
        path.write_text(text, encoding="utf-8")


def require_replace(text: str, source: str, target: str, label: str) -> str:
    if source not in text:
        raise RuntimeError(f"upstream UI changed at {label}; review before building")
    return text.replace(source, target, 1)


def patch_pair_code(lib_rs: Path) -> None:
    text = lib_rs.read_text(encoding="utf-8")
    start = text.find("fn random_pairing_code() -> String {")
    if start < 0:
        raise RuntimeError("upstream random_pairing_code() not found")
    end_marker = "\n}\n\n#[cfg(test)]"
    end = text.find(end_marker, start)
    if end < 0:
        raise RuntimeError("could not determine random_pairing_code() boundary")
    old_function = text[start : end + 2]
    if "1_000_000" not in old_function:
        raise RuntimeError("upstream pairing implementation changed; review before building")

    new_function = r'''fn random_pairing_code() -> String {
    // Human-facing pairing code: 12 unambiguous base32 characters grouped as
    // XXXX-XXXX-XXXX. Avoid O/0/I/1 so a user can read it across two screens.
    const ALPHABET: &[u8] = b"ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
    let rng = SystemRandom::new();
    let mut bytes = [0_u8; 12];
    if rng.fill(&mut bytes).is_err() {
        let seed = now_ms().to_le_bytes();
        for (index, byte) in bytes.iter_mut().enumerate() {
            *byte = seed[index % seed.len()].wrapping_add(index as u8 * 37);
        }
    }

    let mut raw = String::with_capacity(12);
    for byte in bytes {
        raw.push(ALPHABET[(byte as usize) % ALPHABET.len()] as char);
    }
    format!("{}-{}-{}", &raw[0..4], &raw[4..8], &raw[8..12])
}'''
    lib_rs.write_text(text[:start] + new_function + text[end + 2 :], encoding="utf-8")


def patch_pairing_ui(app_tsx: Path, i18n_ts: Path) -> None:
    text = app_tsx.read_text(encoding="utf-8")
    old_handler = '''setServerPairingCode(
                  event.target.value.replace(/\\D/g, "").slice(0, 6),
                );'''
    new_handler = '''const raw = event.target.value
                  .toUpperCase()
                  .replace(/[^A-HJ-NP-Z2-9]/g, "")
                  .slice(0, 12);
                setServerPairingCode(raw.replace(/(.{4})(?=.)/g, "$1-"));'''
    text = require_replace(text, old_handler, new_handler, "pairing input formatter")

    pairing_input_marker = '''              inputMode="numeric"
              autoComplete="one-time-code"
              placeholder={ui.devices.pairingCodePlaceholder}'''
    pairing_input_replacement = '''              inputMode="text"
              autoCapitalize="characters"
              spellCheck={false}
              maxLength={14}
              autoComplete="one-time-code"
              placeholder={ui.devices.pairingCodePlaceholder}'''
    text = require_replace(text, pairing_input_marker, pairing_input_replacement, "pairing input attributes")
    text = require_replace(
        text,
        'disabled={isPairingDevice || serverPairingCode.length < 6}',
        'disabled={isPairingDevice || serverPairingCode.length !== 14}',
        "pairing submit validation",
    )
    app_tsx.write_text(text, encoding="utf-8")

    replace_text(
        i18n_ts,
        [
            ("客户端屏幕上会显示 6 位验证码：", "另一台电脑会显示配对码（XXXX-XXXX-XXXX）："),
            ("pairingCodePlaceholder: \"6 位验证码\"", "pairingCodePlaceholder: \"XXXX-XXXX-XXXX\""),
            ("请输入客户端显示的 6 位验证码。", "请输入另一台电脑显示的完整配对码（XXXX-XXXX-XXXX）。"),
            ("The client shows a 6-digit pairing code:", "The other computer shows a pairing code (XXXX-XXXX-XXXX):"),
            ("pairingCodePlaceholder: \"6-digit code\"", "pairingCodePlaceholder: \"XXXX-XXXX-XXXX\""),
            ("Enter the 6-digit code shown on the client.", "Enter the full pairing code shown on the other computer (XXXX-XXXX-XXXX)."),
        ],
    )


def patch_product_ux(app_tsx: Path, i18n_ts: Path, css_path: Path, overlay_css: Path) -> None:
    text = app_tsx.read_text(encoding="utf-8")

    # The first screen after selecting a host must be connection, not an empty
    # topology canvas. Start the native runtime automatically for either role.
    text = require_replace(
        text,
        'setActiveTab(machineRole === "client" ? "settings" : "layout");',
        'setActiveTab(machineRole === "client" ? "settings" : "devices");',
        "role landing tab",
    )
    text = require_replace(
        text,
        '''    if (machineRole === "client" && !runtime?.started) {
      await setRuntimeState(true);
    }''',
        '''    if (!runtime?.started) {
      await setRuntimeState(true);
    }''',
        "automatic runtime start",
    )

    # Never show the generic upstream "mk" badge. The same specified product
    # icon is used in the window, installer and macOS bundle.
    text = require_replace(
        text,
        '<span className="brand-mark">mk</span>',
        '<img className="brand-logo" src="/app-icon.png" alt="视饭AI:主机共享" />',
        "brand icon",
    )
    text = text.replace('<p className="eyebrow">mykvm</p>', '<p className="eyebrow">视饭AI</p>')
    text = text.replace('<span>Server</span>', '<span>主控电脑</span>', 1)
    text = text.replace('<span>Client</span>', '<span>被控电脑</span>', 1)
    text = text.replace('aria-label="mykvm sections"', 'aria-label="视饭AI主机共享功能"')
    text = require_replace(
        text,
        '{runtime.started ? <StopIcon /> : <PlayIcon />}',
        '''<span className="runtime-toggle-icon">
              {runtime.started ? <StopIcon /> : <PlayIcon />}
            </span>
            <span className="runtime-toggle-label">
              {runtime.started ? "停止共享" : "开始共享"}
            </span>''',
        "runtime button label",
    )

    # Host page: make the normal path obvious and move all mental load away from
    # raw IP/port fields. Manual addressing remains in the backend for support,
    # but is not the primary path shown to ordinary users.
    text = require_replace(
        text,
        '          <div className="connection-stack">',
        '''          <section className="quick-start-guide" aria-label="三步连接电脑">
            <div><span>1</span><strong>另一台选择“被控电脑”</strong><p>两台电脑都打开本软件，并保持在同一个局域网。</p></div>
            <div><span>2</span><strong>点击“自动查找另一台电脑”</strong><p>不需要输入 IP，也不需要配置端口。</p></div>
            <div><span>3</span><strong>找到后点击连接</strong><p>输入另一台电脑显示的 XXXX-XXXX-XXXX 配对码即可。</p></div>
          </section>

          <div className="connection-stack">''',
        "host quick start guide",
    )

    # Client page: put a single, large instruction card before advanced settings.
    text = require_replace(
        text,
        '          <div className="settings-layout">',
        '''          {machineRole === "client" ? (
            <section className="client-wait-card">
              <div className={`client-wait-dot ${runtime.started ? "ready" : "stopped"}`} />
              <div className="client-wait-copy">
                <p className="eyebrow">被控电脑</p>
                <h2>{runtime.pairing.state === "requested" ? "主控电脑正在请求连接" : "等待主控电脑连接"}</h2>
                <p>保持本软件打开，然后回到主控电脑点击“连接电脑 → 自动查找另一台电脑”。找到本机后点击连接。</p>
                <small>配对请求到达后，这里会自动弹出 XXXX-XXXX-XXXX 配对码。</small>
              </div>
              <strong className="client-wait-status">{runtime.started ? "接收服务已启动" : "接收服务未启动"}</strong>
            </section>
          ) : null}

          <div className="settings-layout">''',
        "client waiting guide",
    )
    app_tsx.write_text(text, encoding="utf-8")

    replace_text(
        i18n_ts,
        [
            ('layout: "布局"', 'layout: "屏幕位置"'),
            ('devices: "设备"', 'devices: "连接电脑"'),
            ('server: "服务端"', 'server: "主控电脑"'),
            ('client: "客户端"', 'client: "被控电脑"'),
            ('title: "正在载入 视饭AI:主机共享"', 'title: "正在启动视饭AI:主机共享"'),
            ('copy: "读取本机配置、显示器布局和桌面运行状态。"', 'copy: "正在检测本机屏幕、网络和键鼠服务，请稍候。"'),
            ('eyebrow: "视饭AI:主机共享 setup"', 'eyebrow: "第一次使用"'),
            ('title: "选择这台设备的工作模式"', 'title: "这台电脑连接着你正在使用的键盘鼠标吗？"'),
            ('copy: "服务端负责发现并添加其它设备；客户端保持轻量运行，只接收服务端共享过来的鼠标和键盘。"', 'copy: "两台电脑都安装本软件，每台只需要选择一次。后面可以在设置里修改。"'),
            ('serverTitle: "服务端"', 'serverTitle: "是，这台是主控电脑"'),
            ('serverCopy: "进入完整工作台，添加局域网设备并管理显示器布局。"', 'serverCopy: "键盘和鼠标插在这台电脑，用它控制另一台电脑。"'),
            ('clientTitle: "客户端"', 'clientTitle: "不是，这台是被控电脑"'),
            ('clientCopy:\n        "进入精简状态页，默认仅接收远端键鼠输入，适合被控设备常驻后台。"', 'clientCopy:\n        "这台电脑不需要另一套键盘鼠标，只接收主控电脑的操作。"'),
            ('title: "显示器布局"', 'title: "屏幕位置"'),
            ('addDevice: "添加设备"', 'addDevice: "连接另一台电脑"'),
            ('title: "连接设备"', 'title: "连接另一台电脑"'),
            ('subtitle:\n        "扫描局域网设备，或输入 IP 手动连接。只有识别到屏幕信息的设备才会加入布局。"', 'subtitle:\n        "正常使用只需要自动查找，不需要输入 IP 或端口。"'),
            ('addTitle: "添加设备"', 'addTitle: "自动查找"'),
            ('addCopy: "先扫描局域网，没扫到再输入 IP 手动连接。"', 'addCopy: "先确认另一台电脑已选择“被控电脑”并保持软件打开。"'),
            ('scanLan: "扫描局域网"', 'scanLan: "自动查找另一台电脑"'),
            ('scanning: "扫描中"', 'scanning: "正在查找"'),
            ('scanningTitle: "正在扫描局域网"', 'scanningTitle: "正在查找另一台电脑"'),
            ('scanningCopy: "正在搜索同网络下的 视饭AI:主机共享 设备…"', 'scanningCopy: "正在搜索同一局域网里的视饭AI:主机共享…"'),
            ('pair: "配对"', 'pair: "连接这台电脑"'),
            ('repair: "重新配对"', 'repair: "重新连接"'),
            ('serverPairingTitle: "输入客户端验证码"', 'serverPairingTitle: "输入另一台电脑的配对码"'),
            ('clientPairingTitle: "服务端请求配对"', 'clientPairingTitle: "主控电脑正在连接这台电脑"'),
            ('clientPairingCopy: "在服务端输入上方验证码完成连接。"', 'clientPairingCopy: "把上面的配对码输入到主控电脑，即可完成连接。"'),
            ('confirmPairing: "确认配对"', 'confirmPairing: "确认连接"'),
            ('listTitle: "设备列表"', 'listTitle: "找到的电脑"'),
            ('title: "设置"', 'title: "设置与排障"'),
            ('subtitle: "工作模式、传输端口、语言主题、剪贴板同步和本机状态。"', 'subtitle: "普通使用无需修改这里；只有排障或个性化设置时再调整。"'),
            ('roleTitle: "工作模式"', 'roleTitle: "这台电脑的角色"'),
            ('roleCopy:\n        "服务端负责管理布局并捕获输入；客户端保持轻量常驻，接收远端键鼠。"', 'roleCopy:\n        "主控电脑连接键盘鼠标；被控电脑只负责接收操作。"'),
        ],
    )

    if overlay_css.exists():
        css = css_path.read_text(encoding="utf-8")
        marker = "/* SHIFANAI_PRODUCT_OVERRIDES */"
        if marker not in css:
            css += "\n\n" + marker + "\n" + overlay_css.read_text(encoding="utf-8") + "\n"
            css_path.write_text(css, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--repo", required=True, help="owner/repo")
    args = parser.parse_args()

    root = args.root.resolve()
    version = args.version.strip()
    repo_url = f"https://github.com/{args.repo}"
    script_root = Path(__file__).resolve().parent

    package_path = root / "package.json"
    package = load_json(package_path)
    package["name"] = PACKAGE_NAME
    package["version"] = version
    package["repository"] = {"type": "git", "url": repo_url + ".git"}
    save_json(package_path, package)

    tauri_path = root / "src-tauri" / "tauri.conf.json"
    tauri = load_json(tauri_path)
    tauri["productName"] = PRODUCT_FS_NAME
    tauri["version"] = version
    tauri["identifier"] = IDENTIFIER
    windows = tauri.setdefault("app", {}).setdefault("windows", [])
    for window in windows:
        window["title"] = PRODUCT_TITLE
        # The simplified workflow needs enough width for clear Chinese copy,
        # without opening as a huge full-screen dashboard.
        window["width"] = max(int(window.get("width", 1180)), 1180)
        window["height"] = max(int(window.get("height", 760)), 760)
        window["minWidth"] = 980
        window["minHeight"] = 680
    bundle = tauri.setdefault("bundle", {})
    bundle["createUpdaterArtifacts"] = False
    updater = tauri.setdefault("plugins", {}).get("updater")
    if isinstance(updater, dict):
        updater["endpoints"] = [repo_url + "/releases/latest/download/latest.json"]
    save_json(tauri_path, tauri)

    mac_path = root / "src-tauri" / "tauri.macos.conf.json"
    if mac_path.exists():
        mac = load_json(mac_path)
        for window in mac.setdefault("app", {}).setdefault("windows", []):
            window["title"] = PRODUCT_TITLE
        save_json(mac_path, mac)

    cargo_path = root / "src-tauri" / "Cargo.toml"
    cargo = cargo_path.read_text(encoding="utf-8")
    cargo = re.sub(r'(?m)^version = "[^"]+"$', f'version = "{version}"', cargo, count=1)
    cargo = cargo.replace(
        'description = "A cross-platform software KVM prototype"',
        'description = "ShifanAI cross-platform software KVM"',
    )
    cargo = cargo.replace(
        'repository = "https://github.com/XxMinor/mykvm"',
        f'repository = "{repo_url}"',
    )
    cargo_path.write_text(cargo, encoding="utf-8")

    # Rebrand visible strings while keeping protocol/local-storage identifiers
    # untouched, so the pinned native core remains internally consistent.
    for relative in ["src/App.tsx", "src/i18n.ts", "index.html"]:
        replace_text(root / relative, [("MyKVM", PRODUCT_TITLE)])

    replace_text(root / "src-tauri" / "src" / "lib.rs", [(UPSTREAM_REPO, repo_url)])
    replace_text(root / "src-tauri" / "nsis-hooks.nsh", [("MyKVM", "ShifanAI Host Share")])
    replace_text(root / "src" / "constants.ts", [(UPSTREAM_REPO, repo_url)])

    patch_pair_code(root / "src-tauri" / "src" / "lib.rs")
    patch_pairing_ui(root / "src" / "App.tsx", root / "src" / "i18n.ts")
    patch_product_ux(
        root / "src" / "App.tsx",
        root / "src" / "i18n.ts",
        root / "src" / "App.css",
        script_root / "product_overrides.css",
    )
    replace_text(
        root / "src-tauri" / "src" / "lib.rs",
        [("const PAIRING_CODE_TTL_MS: u64 = 60_000;", "const PAIRING_CODE_TTL_MS: u64 = 180_000;")],
    )

    print(f"Native product overlay complete: version={version} repo={args.repo}")


if __name__ == "__main__":
    main()
