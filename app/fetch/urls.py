import asyncio
import ipaddress
import socket
from collections.abc import Callable
from urllib.parse import urlsplit, urlunsplit

from app.fetch.errors import UnsafeUrlError
from app.fetch.policy import FetchPolicy

ALLOWED_SCHEMES = ("http", "https")

Resolver = Callable[[str], list[str]]


def system_resolver(host: str) -> list[str]:
    infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    return [str(info[4][0]) for info in infos]


def origin_of(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, "", "", ""))


def is_public_address(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    )


async def ensure_safe_url(
    url: str, policy: FetchPolicy, resolver: Resolver = system_resolver
) -> str:
    parts = urlsplit(url)
    if parts.scheme not in ALLOWED_SCHEMES:
        raise UnsafeUrlError(f"scheme not allowed: {parts.scheme or '(none)'}")

    host = parts.hostname
    if not host:
        raise UnsafeUrlError(f"no host in url: {url}")
    if policy.allow_private_hosts:
        return url

    try:
        addresses = await asyncio.to_thread(resolver, host)
    except OSError as exc:
        raise UnsafeUrlError(f"cannot resolve host: {host}") from exc
    if not addresses:
        raise UnsafeUrlError(f"cannot resolve host: {host}")

    # every address must be public: a name resolving to both is still a way in
    blocked = [address for address in addresses if not is_public_address(address)]
    if blocked:
        raise UnsafeUrlError(f"host {host} resolves to a non-public address: {blocked[0]}")
    return url
