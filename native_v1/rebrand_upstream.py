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
    // XXXX-XXXX-XXXX. This is roughly 60 bits of entropy and avoids O/0/I/1.
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
    """Make the frontend accept and auto-format the new XXXX-XXXX-XXXX code."""
    text = app_tsx.read_text(encoding="utf-8")
    old_handler = '''setServerPairingCode(
                  event.target.value.replace(/\\D/g, "").slice(0, 6),
                );'''
    new_handler = '''const raw = event.target.value
                  .toUpperCase()
                  .replace(/[^A-HJ-NP-Z2-9]/g, "")
                  .slice(0, 12);
                setServerPairingCode(raw.replace(/(.{4})(?=.)/g, "$1-"));'''
    if old_handler not in text:
        raise RuntimeError("upstream pairing input handler changed; review before building")
    text = text.replace(old_handler, new_handler, 1)

    pairing_input_marker = '''              inputMode="numeric"
              autoComplete="one-time-code"
              placeholder={ui.devices.pairingCodePlaceholder}'''
    pairing_input_replacement = '''              inputMode="text"
              autoCapitalize="characters"
              spellCheck={false}
              maxLength={14}
              autoComplete="one-time-code"
              placeholder={ui.devices.pairingCodePlaceholder}'''
    if pairing_input_marker not in text:
        raise RuntimeError("upstream pairing input attributes changed; review before building")
    text = text.replace(pairing_input_marker, pairing_input_replacement, 1)

    disabled_old = "disabled={isPairingDevice || serverPairingCode.length < 6}"
    disabled_new = "disabled={isPairingDevice || serverPairingCode.length !== 14}"
    if disabled_old not in text:
        raise RuntimeError("upstream pairing submit validation changed; review before building")
    text = text.replace(disabled_old, disabled_new, 1)
    app_tsx.write_text(text, encoding="utf-8")

    # Keep the visible help text aligned with the actual code format. The UI is
    # bilingual, so patch both current Chinese and English upstream strings.
    replace_text(
        i18n_ts,
        [
            ("客户端屏幕上会显示 6 位验证码：", "客户端屏幕上会显示配对码（XXXX-XXXX-XXXX）："),
            ("pairingCodePlaceholder: \"6 位验证码\"", "pairingCodePlaceholder: \"XXXX-XXXX-XXXX\""),
            ("请输入客户端显示的 6 位验证码。", "请输入客户端显示的完整配对码（XXXX-XXXX-XXXX）。"),
            ("The client shows a 6-digit pairing code:", "The client shows a pairing code (XXXX-XXXX-XXXX):"),
            ("pairingCodePlaceholder: \"6-digit code\"", "pairingCodePlaceholder: \"XXXX-XXXX-XXXX\""),
            ("Enter the 6-digit code shown on the client.", "Enter the full pairing code shown on the client (XXXX-XXXX-XXXX)."),
        ],
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--repo", required=True, help="owner/repo")
    args = parser.parse_args()

    root = args.root.resolve()
    version = args.version.strip()
    repo_url = f"https://github.com/{args.repo}"

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

    # Rebrand user-visible UI only. Internal protocol/local-storage identifiers
    # remain unchanged so the pinned native core stays internally consistent.
    for relative in ["src/App.tsx", "src/i18n.ts", "index.html"]:
        replace_text(root / relative, [("MyKVM", PRODUCT_TITLE)])

    replace_text(root / "src-tauri" / "src" / "lib.rs", [(UPSTREAM_REPO, repo_url)])
    replace_text(root / "src-tauri" / "nsis-hooks.nsh", [("MyKVM", "ShifanAI Host Share")])
    replace_text(root / "src" / "constants.ts", [(UPSTREAM_REPO, repo_url)])

    patch_pair_code(root / "src-tauri" / "src" / "lib.rs")
    patch_pairing_ui(root / "src" / "App.tsx", root / "src" / "i18n.ts")
    replace_text(
        root / "src-tauri" / "src" / "lib.rs",
        [("const PAIRING_CODE_TTL_MS: u64 = 60_000;", "const PAIRING_CODE_TTL_MS: u64 = 180_000;")],
    )

    # Keep CI output ASCII-only because Git-Bash Python on some Windows runners
    # can inherit a cp1252 stdout encoding even though all source files are UTF-8.
    print(f"Native rebrand complete: version={version} repo={args.repo}")


if __name__ == "__main__":
    main()
