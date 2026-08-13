from __future__ import annotations

import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shifan_host_share.deskflow_engine import _write_settings, build_server_config  # noqa: E402
from shifan_host_share.lan_bridge import probe_tcp  # noqa: E402


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: smoke_deskflow_server.py <deskflow-core>", file=sys.stderr)
        return 2

    core = Path(sys.argv[1]).resolve()
    if not core.exists():
        print(f"Deskflow core missing: {core}", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory(prefix="shifan-deskflow-smoke-") as tmp:
        runtime = Path(tmp)
        server_config = runtime / "deskflow-server.conf"
        settings = runtime / "deskflow-server-settings.ini"
        peers = {
            "left": "PAIR-LEFT",
            "right": "PAIR-RIGHT",
            "up": "PAIR-UP",
            "down": "PAIR-DOWN",
        }
        server_config.write_text(build_server_config("HOST-SMOKE", peers), encoding="utf-8")
        _write_settings(
            settings,
            computer_name="HOST-SMOKE",
            port=24855,
            server_config=server_config,
            interface="127.0.0.1",
        )

        settings_text = settings.read_text(encoding="utf-8")
        external_line = next((line for line in settings_text.splitlines() if line.startswith("externalConfigFile=")), "")
        if not external_line:
            print("externalConfigFile missing from generated settings", file=sys.stderr)
            return 3
        if "\\" in external_line:
            print(f"unsafe Windows path in settings: {external_line}", file=sys.stderr)
            return 3
        if "interface=127.0.0.1" not in settings_text:
            print("loopback interface missing from backend settings", file=sys.stderr)
            return 3

        proc = subprocess.Popen(
            [str(core), "server", "--settings", str(settings)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        try:
            deadline = time.monotonic() + 10.0
            last_probe = ""
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    output = proc.stdout.read() if proc.stdout else ""
                    print(output, file=sys.stderr)
                    return 4
                result = probe_tcp("127.0.0.1", 24855, timeout=0.4)
                if result.ok:
                    print("Deskflow server opened a real TCP listener on 127.0.0.1:24855")
                    print(external_line)
                    return 0
                last_probe = result.error
                time.sleep(0.2)

            print(f"Deskflow process stayed alive but never listened on TCP 24855: {last_probe}", file=sys.stderr)
            if proc.stdout:
                try:
                    print(proc.stdout.read(), file=sys.stderr)
                except Exception:
                    pass
            return 5
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=3)


if __name__ == "__main__":
    raise SystemExit(main())
