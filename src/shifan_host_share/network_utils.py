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
    seen: set[str] = set()
    items: list[tuple[int, str, str]] = []
    if psutil is not None:
        for iface, ip, _ in _iter_private_ipv4() or []:
            if ip in seen:
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


def vpn_adapters() -> list[LanAddress]:
    found: list[LanAddress] = []
    for iface, ip, _ in _iter_private_ipv4() or []:
        low = iface.lower()
        if any(hint in low for hint in VPN_HINTS):
            found.append(LanAddress(iface, ip, False))
    return found


def is_virtual_interface(interface: str) -> bool:
    low = interface.lower()
    return any(hint in low for hint in VIRTUAL_HINTS)


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


def source_candidates_for(peer_ip: str, peer_port: int = 35999) -> list[str | None]:
    candidates: list[str | None] = []
    try:
        routed = route_ip_to(peer_ip, peer_port)
        if routed and routed != "0.0.0.0":
            candidates.append(routed)
    except OSError:
        pass
    addresses = list_lan_addresses()
    physical = [a.ip for a in addresses if not is_virtual_interface(a.interface)]
    virtual = [a.ip for a in addresses if is_virtual_interface(a.interface)]
    for ip in physical + virtual:
        if ip not in candidates:
            candidates.append(ip)
    # Final fallback lets Windows choose the source address itself. This helps on
    # machines whose route table changes after a VPN reconnect.
    candidates.append(None)
    return candidates


def same_local_subnet(peer_ip: str) -> bool:
    if psutil is None:
        return True
    try:
        peer = ipaddress.ip_address(peer_ip)
    except ValueError:
        return False
    for _, ip, netmask in _iter_private_ipv4() or []:
        if not netmask:
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
        raise ValueError("请输入第二台电脑显示的 IPv4 地址") from exc
    if ip.version != 4 or ip.is_loopback or ip.is_multicast or ip.is_unspecified:
        raise ValueError("请输入局域网中的 IPv4 地址")
    return value
