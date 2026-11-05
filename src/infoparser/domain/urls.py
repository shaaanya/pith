"""URL canonicalisation (the dedupe key only) and platform detection."""
from urllib.parse import parse_qsl, urlencode, urlsplit

_TRACKING = ("utm_",)
_TRACKING_EXACT = {"fbclid", "igshid", "si", "gclid"}
_YT = {"youtube.com", "youtu.be", "youtube-nocookie.com"}
_PLATFORMS = {
    "youtube.com": "youtube", "youtu.be": "youtube",
    "instagram.com": "instagram",
    "tiktok.com": "tiktok",
    "reddit.com": "reddit", "redd.it": "reddit",
    "twitter.com": "twitter", "x.com": "twitter", "t.co": "twitter",
    "github.com": "github",
}


def _host(netloc: str) -> str:
    host = netloc.lower().rsplit("@", 1)[-1]
    for p in ("www.", "m."):
        if host.startswith(p):
            host = host[len(p):]
    return host


def canonicalize_url(url: str) -> str:
    """Dedupe key: https, no www/tracking params, sorted query. Never used to fetch or cite."""
    s = urlsplit(url.strip())
    host = _host(s.netloc)
    path = s.path.rstrip("/")
    q = [
        (k, v)
        for k, v in parse_qsl(s.query, keep_blank_values=True)
        if not k.lower().startswith(_TRACKING) and k.lower() not in _TRACKING_EXACT
    ]
    if host == "youtu.be" and path:
        host, q, path = "youtube.com", [("v", path.lstrip("/"))] + q, "/watch"
    elif host in _YT:
        host = "youtube.com"
    query = urlencode(sorted(q))
    return f"https://{host}{path}" + (f"?{query}" if query else "")


def detect_platform(url: str | None) -> str:
    """Name of a known platform for the URL, 'web' for other http(s), else 'unknown'."""
    if not url:
        return "unknown"
    s = urlsplit(url.strip())
    if s.scheme not in ("http", "https") or not s.netloc:
        return "unknown"
    host = _host(s.netloc)
    for dom, name in _PLATFORMS.items():
        if host == dom or host.endswith("." + dom):
            return name
    return "web"
