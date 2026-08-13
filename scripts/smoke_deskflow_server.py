from __future__ import annotations

import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shifan_host_share.deskflow_engine import _write_settings, build_server_config  # noqa: E402


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
        _write_settings(settings, computer_name="HOST-SMOKE", port=24855, server_config=server_config)

        settings_text = settings.read_text(encoding="utf-8")
        external_line = next(
            (line for line in settings_text.splitlines() if line.startswith("externalConfigFile=")),
            "",
        )
        if not external_line:
            print("externalConfigFile missing from generated settings", file=sys.stderr)
            return 3
        if "\\" in external_line:
            print(f"unsafe Windows path in settings: {external_line}", file=sys.stderr)
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
            time.sleep(3.0)
            output = ""
            if proc.poll() is not None:
                output = proc.stdout.read() if proc.stdout else ""
                print(output, file=sys.stderr)
                return 4

            print("Deskflow server stayed alive with generated settings")
            print(external_line)
            return 0
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
