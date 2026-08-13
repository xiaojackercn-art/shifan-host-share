from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass

try:
    import psutil
except Exception:  # pragma: no cover
    psutil = None

VPN_HINTS = ("vpn", "proton", "wireguard", "tailscale", "zerotier", "tap", "tun")
VIRTUAL_HINTS = VPN_HINTS + ("vethernet", "hyper-v", "vmware", "virtualbox", "wsl")


@dataclass(frozen=True)
class LanAddress:
    interface: str
    ip: str
    recommended: bool = False
    virtual: bool = False


def is_virtual_interface(interface: str) -> bool:
    low = interface.lower()
    return any(hint in low for hint in VIRTUAL_HINTS)


def _score(interface: str, ip: str) -> int:
    name = interface.lower()
    score = -200 if is_virtual_interface(interface) else 0
    if "wi-fi" in name or "wifi" in name or "wlan" in name:
        score += 40
    if "ethernet" in name or "以太网" in name or name.startswith("en"):
        score += 45
    if ip.startswith("192.168."):
        score += 50
    elif ip.startswith("172."):
        score += 25
    elif ip.startswith("10."):
        score += 20
    return score


def _iter_private_ipv4():
    if psutil is None:
        return
    stats = psutil.net_if_stats()
    for iface, addrs in psutil.net_if_addrs().items():
        stat = stats.get(iface)
        if stat is not None and not stat.isup:
            continue
        for addr in addrs:
            if addr.family != socket.AF_INET:
                continue
            ip = addr.address
            try:
                parsed = ipaddress.ip_address(ip)
            except ValueError:
                continue
            if parsed.is_loopback or parsed.is_link_local or not parsed.is_private:
                continue
            yield iface, ip, addr.netmask


def list_lan_addresses() -> list[LanAddress]:
    items: list[tuple[int, str, str, bool]] = []
    seen: set[str] = set()
    for iface, ip, _ in _iter_private_ipv4() or []:
        if ip in seen:
            continue
        seen.add(ip)
        items.append((_score(iface, ip), iface, ip, is_virtual_interface(iface)))
    if not items:
        try:
            for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET, socket.SOCK_STREAM):
                ip = info[4][0]
                if ip in seen:
                    continue
                parsed = ipaddress.ip_address(ip)
                if parsed.is_private and not parsed.is_loopback and not parsed.is_link_local:
                    seen.add(ip)
                    items.append((_score("网络适配器", ip), "网络适配器", ip, False))
        except OSError:
            pass
    items.sort(key=lambda x: (-x[0], x[2]))
    return [LanAddress(iface, ip, i == 0 and not virtual, virtual) for i, (_, iface, ip, virtual) in enumerate(items)]


def physical_lan_addresses() -> list[LanAddress]:
    return [item for item in list_lan_addresses() if not item.virtual]


def recommended_ip() -> str:
    physical = physical_lan_addresses()
    if physical:
        return physical[0].ip
    addresses = list_lan_addresses()
    return addresses[0].ip if addresses else "127.0.0.1"


def route_ip_to(peer_ip: str, peer_port: int = 35999) -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect((peer_ip, int(peer_port)))
        return str(sock.getsockname()[0])
    finally:
        sock.close()


def same_local_subnet(peer_ip: str) -> bool:
    if psutil is None:
        return True
    try:
        peer = ipaddress.ip_address(peer_ip)
    except ValueError:
        return False
    for iface, ip, netmask in _iter_private_ipv4() or []:
        if is_virtual_interface(iface) or not netmask:
            continue
        try:
            network = ipaddress.ip_network(f"{ip}/{netmask}", strict=False)
        except ValueError:
            continue
        if peer in network:
            return True
    return False


def validate_peer_ip(value: str) -> str:
    value = value.strip()
    try:
        ip = ipaddress.ip_address(value)
    except ValueError as exc:
        raise ValueError("请输入主控电脑显示的 IPv4 地址") from exc
    if ip.version != 4 or ip.is_loopback or ip.is_multicast or ip.is_unspecified:
        raise ValueError("请输入局域网中的 IPv4 地址")
    return value
