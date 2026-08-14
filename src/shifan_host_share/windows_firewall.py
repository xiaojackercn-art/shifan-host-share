from __future__ import annotations

import ctypes
import os
import platform
import subprocess
from pathlib import Path

RULE_PREFIX = "ShifanAI-HostShare-TCP-24800"


def _rule_name(direction: str) -> str:
    direction = direction.lower()
    if direction not in {"in", "out"}:
        raise ValueError("direction must be 'in' or 'out'")
    return f"{RULE_PREFIX}-{'IN' if direction == 'in' else 'OUT'}"


def build_firewall_rule_args(direction: str, port: int) -> list[str]:
    direction = direction.lower()
    name = _rule_name(direction)
    base = [
        "advfirewall",
        "firewall",
        "add",
        "rule",
        f"name={name}",
        f"dir={direction}",
        "action=allow",
        "protocol=TCP",
        "profile=any",
        "remoteip=any",
        "enable=yes",
    ]
    if direction == "in":
        base.append(f"localport={int(port)}")
    else:
        base.append(f"remoteport={int(port)}")
    return base


def _creationflags() -> int:
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0)) if platform.system() == "Windows" else 0


def _is_admin() -> bool:
    if platform.system() != "Windows":
        return True
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _powershell() -> str:
    root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    candidate = root / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    return str(candidate if candidate.exists() else "powershell.exe")


def _netsh() -> str:
    root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    candidate = root / "System32" / "netsh.exe"
    return str(candidate if candidate.exists() else "netsh.exe")


def firewall_rule_ready(direction: str, port: int) -> tuple[bool, str]:
    """Verify the effective Windows Defender Firewall rule without localization-sensitive parsing."""
    if platform.system() != "Windows":
        return True, "非 Windows 系统无需配置 Windows 防火墙"

    direction = direction.lower()
    name = _rule_name(direction)
    ps_direction = "Inbound" if direction == "in" else "Outbound"
    port_field = "LocalPort" if direction == "in" else "RemotePort"
    script = (
        f"$r = Get-NetFirewallRule -DisplayName '{name}' -ErrorAction SilentlyContinue | "
        f"Where-Object {{ $_.Enabled -eq 'True' -and $_.Direction -eq '{ps_direction}' -and $_.Action -eq 'Allow' }}; "
        "if (-not $r) { exit 2 }; "
        f"$p = $r | Get-NetFirewallPortFilter | Where-Object {{ $_.Protocol -eq 'TCP' -and $_.{port_field} -eq '{int(port)}' }}; "
        "if ($p) { exit 0 } else { exit 3 }"
    )
    try:
        completed = subprocess.run(
            [_powershell(), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=8,
            creationflags=_creationflags(),
            check=False,
        )
    except Exception as exc:
        return False, f"无法读取 Windows 防火墙状态：{exc}"
    if completed.returncode == 0:
        return True, f"Windows 防火墙 {ps_direction} TCP {int(port)} 规则已启用"
    return False, f"Windows 防火墙缺少可用的 {ps_direction} TCP {int(port)} 规则"


def _add_rule(direction: str, port: int) -> tuple[bool, str]:
    args = build_firewall_rule_args(direction, port)
    if _is_admin():
        try:
            completed = subprocess.run(
                [_netsh(), *args],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
                creationflags=_creationflags(),
                check=False,
            )
        except Exception as exc:
            return False, f"自动配置 Windows 防火墙失败：{exc}"
        if completed.returncode == 0:
            return True, "Windows 防火墙规则已写入"
        return False, (completed.stdout or "netsh 返回失败").strip()

    # Installed builds already create the rule with administrator rights.  The
    # elevation path below mainly makes the portable ZIP self-contained: the
    # first time a host/client really needs the rule, Windows asks for UAC once.
    arg_line = " ".join(args).replace("'", "''")
    netsh = _netsh().replace("'", "''")
    script = (
        f"$p = Start-Process -FilePath '{netsh}' -ArgumentList '{arg_line}' "
        "-Verb RunAs -WindowStyle Hidden -Wait -PassThru; exit $p.ExitCode"
    )
    try:
        completed = subprocess.run(
            [_powershell(), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=45,
            creationflags=_creationflags(),
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, "等待 Windows 防火墙授权超时"
    except Exception as exc:
        return False, f"无法请求 Windows 防火墙授权：{exc}"
    if completed.returncode == 0:
        return True, "Windows 防火墙规则已写入"
    return False, "Windows 防火墙授权未完成或被取消"


def ensure_windows_firewall(direction: str, port: int) -> tuple[bool, str]:
    """Ensure a broad TCP rule for the host/client transport.

    v0.8 used ``remoteip=LocalSubnet``.  That scope can behave unexpectedly on
    Windows machines with multiple adapters, public-network profiles or stale
    routes.  v0.9 deliberately uses ``remoteip=any`` while keeping the rule
    restricted to the single Deskflow TCP port.  The listener itself only
    exists while sharing is active.
    """
    if platform.system() != "Windows":
        return True, ""
    ready, detail = firewall_rule_ready(direction, port)
    if ready:
        return True, detail
    installed, install_detail = _add_rule(direction, port)
    if not installed:
        return False, install_detail
    ready, verify_detail = firewall_rule_ready(direction, port)
    if not ready:
        return False, f"防火墙规则写入后验证失败：{verify_detail}"
    return True, verify_detail
