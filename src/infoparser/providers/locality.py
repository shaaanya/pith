"""Where a backend runs. Loopback is local; any other host counts as remote unless declared."""

import ipaddress
from urllib.parse import urlsplit

LOCALITIES = ("local", "remote")


def is_loopback(url: str) -> bool:
    """True for localhost, 127.0.0.0/8 and ::1 (the only hosts that cannot leave the machine)."""
    host = (urlsplit(url).hostname or "").lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def resolve(spec: dict, url: str | None = None) -> str:
    """The backend locality: validated if declared, else inferred from its base URL.

    A backend with a URL and no declaration is remote unless the host is loopback. Backends
    without a URL (a local command) default to local; that cannot be detected, so it is trusted.
    """
    declared = spec.get("locality")
    if declared is None:
        return "local" if url is None or is_loopback(url) else "remote"
    if declared not in LOCALITIES:
        raise ValueError(f"locality must be 'local' or 'remote', got {declared!r}")
    return declared


def warnings(backends: dict[str, dict]) -> list[str]:
    """Backends declared local although their base_url points beyond this machine."""
    return [
        f"backend {name!r} declares locality = \"local\" but {spec['base_url']} is not a loopback "
        "address; its traffic leaves this machine and allow_remote does not apply to it"
        for name, spec in backends.items()
        if spec.get("locality") == "local" and spec.get("base_url")
        and not is_loopback(spec["base_url"])
    ]
