from __future__ import annotations

import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shifan_host_share.deskflow_engine import _write_settings, build_server_config  # noqa: E402
from shifan_host_share.lan_bridge import TcpForwarder, probe_tcp  # noqa: E402


def _collect(proc: subprocess.Popen, target: list[str]) -> None:
    if not proc.stdout:
        return
    for raw in proc.stdout:
        line = raw.strip()
        if line:
            target.append(line)
            del target[:-200]


def _terminate(proc: subprocess.Popen | None) -> None:
    if not proc or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=3)


def main() -> int:
    """Verify a real Deskflow listener is reachable through our TCP bridge.

    Deskflow intentionally refuses to start a second core instance on the same
    Windows machine (server + client on one runner), so a single-host CI cannot
    legitimately emulate two physical PCs with two Deskflow cores.  This smoke
    test instead keeps one real Deskflow Server and proves that an external TCP
    socket connected to the ShifanAI-facing port creates a live forwarded
    connection into that real Deskflow listener.
    """
    if len(sys.argv) != 2:
        print("usage: smoke_deskflow_pair.py <deskflow-core>", file=sys.stderr)
        return 2
    core = Path(sys.argv[1]).resolve()
    if not core.exists():
        print(f"Deskflow core missing: {core}", file=sys.stderr)
        return 2

    backend_port = 24856
    public_port = 24857
    server_logs: list[str] = []
    server: subprocess.Popen | None = None
    bridge = TcpForwarder("127.0.0.1", public_port, "127.0.0.1", backend_port)

    with tempfile.TemporaryDirectory(prefix="shifan-deskflow-bridge-") as tmp:
        runtime = Path(tmp)
        conf = runtime / "server.conf"
        settings = runtime / "server.ini"
        peers = {
            "left": "PAIR-LEFT",
            "right": "PAIR-RIGHT",
            "up": "PAIR-UP",
            "down": "PAIR-DOWN",
        }
        conf.write_text(build_server_config("HOST-SMOKE", peers), encoding="utf-8")
        _write_settings(
            settings,
            computer_name="HOST-SMOKE",
            port=backend_port,
            server_config=conf,
            interface="127.0.0.1",
        )

        try:
            server = subprocess.Popen(
                [str(core), "server", "--settings", str(settings)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            threading.Thread(target=_collect, args=(server, server_logs), daemon=True).start()

            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if server.poll() is not None:
                    print("server exited early\n" + "\n".join(server_logs), file=sys.stderr)
                    return 3
                if probe_tcp("127.0.0.1", backend_port, 0.35).ok:
                    break
                time.sleep(0.2)
            else:
                print("server never opened backend listener\n" + "\n".join(server_logs), file=sys.stderr)
                return 4

            ok, message = bridge.start()
            if not ok:
                print(f"bridge failed: {message}", file=sys.stderr)
                return 5

            with socket.create_connection(("127.0.0.1", public_port), timeout=2.0) as external:
                external.settimeout(2.0)
                deadline = time.monotonic() + 2.0
                saw_forwarded_session = False
                while time.monotonic() < deadline:
                    if server.poll() is not None:
                        print("server exited during bridge test\n" + "\n".join(server_logs), file=sys.stderr)
                        return 6
                    if bridge.status()["active_connections"] >= 1:
                        saw_forwarded_session = True
                        break
                    time.sleep(0.05)
                if not saw_forwarded_session:
                    print("public TCP connection never reached Deskflow backend", file=sys.stderr)
                    return 7
                # Keep it open briefly so this is not merely a connect/close race.
                time.sleep(0.35)
                if bridge.status()["active_connections"] < 1:
                    print("forwarded Deskflow TCP connection collapsed immediately", file=sys.stderr)
                    print("\n".join(server_logs[-40:]), file=sys.stderr)
                    return 8

            print("Real Deskflow Server accepted a connection through the ShifanAI TCP bridge")
            return 0
        finally:
            bridge.stop()
            _terminate(server)


if __name__ == "__main__":
    raise SystemExit(main())
