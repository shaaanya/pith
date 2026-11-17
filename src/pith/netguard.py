"""Fetch trust boundary: refuse URLs that point at this machine or its network (SSRF guard).

Untrusted URLs (imported chat content) may only reach public addresses. A direct user submission
may reach a private target only when the submitted host is itself private; a redirect from a public
host to a private one is refused for everyone. The check runs on the resolved addresses (and again
on the connected peer, see `web.py`), so decimal/octal/hex IPv4 forms, IPv4-mapped IPv6 and
hostnames that resolve to private space are all covered.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

UNTRUSTED_ADAPTERS = ("telegram_export",)  # content written by other people, not the user


class BlockedURL(ValueError):
    """The URL points somewhere the fetch trust boundary does not allow."""


def untrusted(row) -> bool:
    """True when the inbox row came from content other people wrote (never the user directly)."""
    return ("adapter" in row.keys()) and row["adapter"] in UNTRUSTED_ADAPTERS


def resolve(host: str) -> list[str]:
    """Every address a hostname resolves to; tests replace this with a stub."""
    try:
        return sorted({i[4][0] for i in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)})
    except OSError as e:
        raise BlockedURL(f"cannot resolve {host!r}: {e}") from e


_V4_EMBEDS = ("64:ff9b::/96", "::/96", "::ffff:0:0:0/96")  # NAT64, v4-compatible, SIIT


def _embedded_v4(ip):
    """The IPv4 address hidden in a mapped, 6to4 or NAT64 IPv6 address, else None."""
    if ip.version != 6:
        return None
    if ip.ipv4_mapped:
        return ip.ipv4_mapped
    if ip.sixtofour:
        return ip.sixtofour
    if any(ip in ipaddress.ip_network(n) for n in _V4_EMBEDS):
        return ipaddress.IPv4Address(ip.packed[-4:])
    return None


def is_public(ip) -> bool:
    """True only for globally routable unicast addresses."""
    inner = _embedded_v4(ip)
    if inner is not None:
        return is_public(inner)
    return ip.is_global and not ip.is_multicast


def _ip(text: str):
    """An address literal as ipaddress sees it, including inet_aton's decimal/octal/hex forms."""
    try:
        return ipaddress.ip_address(text.split("%")[0])
    except ValueError:
        pass
    try:
        return ipaddress.IPv4Address(socket.inet_aton(text))
    except OSError:
        return None


def _addresses(host: str) -> list:
    literal = _ip(host)
    if literal is not None:
        return [literal]
    found = [_ip(a) for a in resolve(host)]
    if not found or None in found:
        raise BlockedURL(f"cannot resolve {host!r}")
    return found


def _host(url: str, allow_userinfo: bool) -> str:
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise BlockedURL(f"unsupported URL: {url!r}")
    if "@" in p.netloc and not allow_userinfo:
        raise BlockedURL(f"credentials in URL refused: {url!r}")
    return p.hostname


def private_target(url: str) -> bool:
    """True when EVERY address of the URL's host is non-public (a deliberately local target)."""
    return not any(is_public(a) for a in _addresses(_host(url, True)))


def check_url(url: str, *, allow_private: bool) -> None:
    """Raise BlockedURL unless the URL may be fetched (allow_private lifts the address test)."""
    host = _host(url, allow_private)
    if allow_private:
        return
    for a in _addresses(host):
        if not is_public(a):
            raise BlockedURL(f"refusing non-public address {a} for {host!r}")


def check_peer(address: str, *, allow_private: bool) -> None:
    """Raise BlockedURL when the address a socket really connected to is not allowed."""
    ip = _ip(address)
    if not allow_private and (ip is None or not is_public(ip)):
        raise BlockedURL(f"refusing connection to non-public address {address}")
