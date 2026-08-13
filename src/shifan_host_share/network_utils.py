from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass

try:
    import psutil
except Exception:  # pragma: no cover
    psutil = None

VIRTUAL_HINTS = ("vpn", "wireguard", "tailscale", "zerotier", "tap", "tun", "vethernet", "hyper-v", "vmware", "virtualbox")


@dataclass(frozen=True)
class LanAddress:
    interface: str
    ip: str
    recommended: bool = False


def _score(interface: str, ip: str) -> int:
    name = interface.lower()
    score = 0
    if any(hint in name for hint in VIRTUAL_HINTS):
        score -= 100
    if "wi-fi" in name or "wifi" in name or "wlan" in name:
        score += 30
    if "ethernet" in name or "以太网" in name or name.startswith("en"):
        score += 35
    if ip.startswith("192.168."):
        score += 40
    elif ip.startswith("172."):
        score += 25
    elif ip.startswith("10."):
        score += 15
    return score


def list_lan_addresses() -> list[LanAddress]:
    seen: set[str] = set()
    items: list[tuple[int, str, str]] = []
    if psutil is not None:
        for iface, addrs in psutil.net_if_addrs().items():
            for addr in addrs:
                if addr.family != socket.AF_INET:
                    continue
                ip = addr.address
                try:
                    parsed = ipaddress.ip_address(ip)
                except ValueError:
                    continue
                if parsed.is_loopback or parsed.is_link_local or not parsed.is_private or ip in seen:
                    continue
                seen.add(ip)
                items.append((_score(iface, ip), iface, ip))
    if not items:
        try:
            for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET, socket.SOCK_STREAM):
                ip = info[4][0]
                if ip in seen:
                    continue
                parsed = ipaddress.ip_address(ip)
                if parsed.is_private and not parsed.is_loopback and not parsed.is_link_local:
                    seen.add(ip)
                    items.append((_score("网络适配器", ip), "网络适配器", ip))
        except OSError:
            pass
    items.sort(key=lambda x: (-x[0], x[2]))
    return [LanAddress(iface, ip, i == 0) for i, (_, iface, ip) in enumerate(items)]


def recommended_ip() -> str:
    addresses = list_lan_addresses()
    return addresses[0].ip if addresses else "127.0.0.1"


def route_ip_to(peer_ip: str, peer_port: int = 35999) -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect((peer_ip, int(peer_port)))
        return str(sock.getsockname()[0])
    finally:
        sock.close()


def validate_peer_ip(value: str) -> str:
    value = value.strip()
    try:
        ip = ipaddress.ip_address(value)
    except ValueError as exc:
        raise ValueError("请输入第二台电脑显示的 IPv4 地址") from exc
    if ip.version != 4 or ip.is_loopback or ip.is_multicast or ip.is_unspecified:
        raise ValueError("请输入局域网中的 IPv4 地址")
    return value
