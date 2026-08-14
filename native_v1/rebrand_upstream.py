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
    old_pattern = re.compile(
        r"fn random_pairing_code\(\) -> String \{\n"
        r"\s*let rng = SystemRandom::new\(\);\n"
        r"\s*let mut bytes = \[0_u8; 4\];\n"
        r"\s*if rng\.fill\(&mut bytes\)\.is_err\(\) \{\n"
        r"\s*bytes = now_ms\(\)\.to_le_bytes\(\)\[\.\.4\]\.try_into\(\)\.unwrap_or\(\[0; 4\]\);\n"
        r"\s*\}\n"
        r"\s*format!\(\"\{:\\?06\}\".*?\n"
        r"\}",
        re.DOTALL,
    )
    # Keep this replacement deliberately simple and guarded. Upstream currently
    # uses a 6 digit numeric challenge. If upstream changes the function, fail
    # loudly instead of silently shipping an unexpected pairing format.
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
    // XXXX-XXXX-XXXX.  This is ~60 bits of entropy and intentionally avoids
    // confusing O/0/I/1 characters.
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
    # Alpha installers should not depend on an updater private signing key.
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
    cargo = cargo.replace('description = "A cross-platform software KVM prototype"',
                          'description = "ShifanAI cross-platform software KVM"')
    cargo = cargo.replace('repository = "https://github.com/XxMinor/mykvm"',
                          f'repository = "{repo_url}"')
    cargo_path.write_text(cargo, encoding="utf-8")

    # Visible frontend branding only. Keep protocol markers / local storage keys
    # named mykvm for wire compatibility with the pinned, audited core.
    for relative in ["src/App.tsx", "src/i18n.ts", "index.html"]:
        replace_text(root / relative, [("MyKVM", PRODUCT_TITLE)])

    # Product-facing URLs and labels in the Rust/Tauri shell.
    replace_text(
        root / "src-tauri" / "src" / "lib.rs",
        [
            (UPSTREAM_REPO, repo_url),
            (UPSTREAM_REPO + "/releases/latest", repo_url + "/releases/latest"),
        ],
    )
    replace_text(
        root / "src-tauri" / "nsis-hooks.nsh",
        [("MyKVM", "ShifanAI Host Share")],
    )

    constants = root / "src" / "constants.ts"
    replace_text(
        constants,
        [
            (UPSTREAM_REPO, repo_url),
            ("0.1.0", version),
        ],
    )

    # Product requirement: human-readable 12-character pairing code.
    patch_pair_code(root / "src-tauri" / "src" / "lib.rs")

    # Give users more time to walk between two physical computers during pairing.
    replace_text(
        root / "src-tauri" / "src" / "lib.rs",
        [("const PAIRING_CODE_TTL_MS: u64 = 60_000;", "const PAIRING_CODE_TTL_MS: u64 = 180_000;")],
    )

    print(f"Rebranded native core at {root}")
    print(f"Product: {PRODUCT_TITLE}")
    print(f"Version: {version}")
    print(f"Repository: {repo_url}")


if __name__ == "__main__":
    main()
