from __future__ import annotations

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


def _spawn(core: Path, role: str, settings: Path, logs: list[str]) -> subprocess.Popen:
    proc = subprocess.Popen(
        [str(core), role, "--settings", str(settings)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    threading.Thread(target=_collect, args=(proc, logs), daemon=True).start()
    return proc


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: smoke_deskflow_pair.py <deskflow-core>", file=sys.stderr)
        return 2
    core = Path(sys.argv[1]).resolve()
    if not core.exists():
        print(f"Deskflow core missing: {core}", file=sys.stderr)
        return 2

    backend_port = 24856
    public_port = 24857
    client_name = "PAIR-RIGHT"
    server_logs: list[str] = []
    client_logs: list[str] = []
    server: subprocess.Popen | None = None
    client: subprocess.Popen | None = None
    bridge = TcpForwarder("127.0.0.1", public_port, "127.0.0.1", backend_port)

    with tempfile.TemporaryDirectory(prefix="shifan-deskflow-pair-") as tmp:
        runtime = Path(tmp)
        conf = runtime / "server.conf"
        server_settings = runtime / "server.ini"
        client_settings = runtime / "client.ini"
        peers = {
            "left": "PAIR-LEFT",
            "right": client_name,
            "up": "PAIR-UP",
            "down": "PAIR-DOWN",
        }
        conf.write_text(build_server_config("HOST-SMOKE", peers), encoding="utf-8")
        _write_settings(
            server_settings,
            computer_name="HOST-SMOKE",
            port=backend_port,
            server_config=conf,
            interface="127.0.0.1",
        )
        _write_settings(
            client_settings,
            computer_name=client_name,
            port=public_port,
            remote_host="127.0.0.1",
        )

        try:
            server = _spawn(core, "server", server_settings, server_logs)
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
            if not probe_tcp("127.0.0.1", public_port, 0.8).ok:
                print("public bridge listener probe failed", file=sys.stderr)
                return 6

            client = _spawn(core, "client", client_settings, client_logs)
            deadline = time.monotonic() + 12
            saw_persistent_bridge = False
            while time.monotonic() < deadline:
                if server.poll() is not None:
                    print("server exited during pair test\n" + "\n".join(server_logs), file=sys.stderr)
                    return 7
                if client.poll() is not None:
                    print("client exited during pair test\n" + "\n".join(client_logs), file=sys.stderr)
                    return 8
                combined = "\n".join(server_logs + client_logs).lower()
                if "unrecognised client" in combined or "server refused client" in combined:
                    print("Deskflow rejected configured client name\n" + combined, file=sys.stderr)
                    return 9
                if bridge.status()["active_connections"] >= 1:
                    # Require the session to remain up for another second rather
                    # than accepting a transient TCP connect/retry.
                    time.sleep(1.2)
                    if bridge.status()["active_connections"] >= 1:
                        saw_persistent_bridge = True
                        break
                time.sleep(0.2)

            if not saw_persistent_bridge:
                print("no persistent Deskflow client/server TCP session formed", file=sys.stderr)
                print("SERVER:\n" + "\n".join(server_logs[-40:]), file=sys.stderr)
                print("CLIENT:\n" + "\n".join(client_logs[-40:]), file=sys.stderr)
                return 10

            print("Deskflow server + ShifanAI bridge + Deskflow client formed a persistent TCP session")
            return 0
        finally:
            _terminate(client)
            bridge.stop()
            _terminate(server)


if __name__ == "__main__":
    raise SystemExit(main())
