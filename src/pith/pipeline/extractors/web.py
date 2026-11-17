"""Web page and Reddit extractor: fetches the URL as submitted, caps size, refuses odd schemes."""

from __future__ import annotations

import http.client
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlparse, urlunparse

from pith import netguard
from pith.pipeline.extractors.base import (
    Extracted,
    ExtractCtx,
    NeedsClarificationError,
    register,
)
from pith.pipeline.htmltext import extract_main

FETCH_TIMEOUT = 20  # seconds; module-level so tests can shorten it
_UA = "Mozilla/5.0 (compatible; Pith/0.1; +local personal knowledge tool)"
_WALL = re.compile(
    r"log ?in to (continue|read|view)|sign ?in to (continue|read|view)|"
    r"subscribe to (continue|read)|subscribers only|"
    r"create (a free )?account to (continue|read)|enable javascript|"
    r"verify you are (a )?human",
    re.I,
)
_REDDIT_PATH = re.compile(r"^/r/[^/]+/comments/")
REDDIT_HOSTS = ("reddit.com",)  # module-level so tests can point it at the fixture server
PASTE = "login or paywall; paste the text"


@dataclass
class FetchResult:
    """A capped HTTP response plus the URL that finally served it."""

    status: int
    content_type: str
    body: bytes
    final_url: str


class _Redirects(urllib.request.HTTPRedirectHandler):
    """Follow redirects only to http(s) targets the trust boundary allows, checked on every hop."""

    def __init__(self, policy):
        self.policy = policy

    # pylint: disable-next=too-many-arguments,too-many-positional-arguments  # urllib's signature
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlparse(newurl).scheme not in ("http", "https"):
            raise urllib.error.URLError(f"refusing redirect to non-http(s) scheme: {newurl}")
        if self.policy.allow_private and not netguard.private_target(newurl):
            self.policy.allow_private = False  # one public hop ends private access for the chain
        netguard.check_url(newurl, allow_private=self.policy.allow_private)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _proxied(req) -> bool:
    """True when a proxy carries the request (https goes through a CONNECT tunnel host)."""
    return req.has_proxy() or bool(req._tunnel_host)  # pylint: disable=protected-access


class _Policy:  # pylint: disable=too-few-public-methods  # shared mutable flag
    """Whether private addresses are still allowed; only true while every hop so far was private."""

    def __init__(self, allow_private: bool):
        self.allow_private = allow_private


def _peer_checked(base, policy, proxied: bool):
    """A connection class that vets the address it really connected to (DNS rebinding).

    ponytail: the TCP/TLS handshake happens before the check (no request is sent). Behind a
    proxy the peer is the proxy, so the peer check is skipped and rebinding is the proxy's
    concern; the pre-connect host check on the target and every hop still applies.
    """
    class Conn(base):  # pylint: disable=too-few-public-methods  # extends an http.client class
        """Refuses to send a request over a connection to a non-public peer."""

        def connect(self):
            """Connect, then refuse a non-public peer before anything is sent."""
            super().connect()
            if proxied:
                return
            try:
                netguard.check_peer(self.sock.getpeername()[0], allow_private=policy.allow_private)
            except netguard.BlockedURL:
                self.close()
                raise

    return Conn


def _opener(policy):
    class Http(urllib.request.HTTPHandler):
        """HTTP over peer-checked connections."""

        def http_open(self, req):
            """Open over a connection that vets its peer."""
            conn = _peer_checked(http.client.HTTPConnection, policy, _proxied(req))
            return self.do_open(conn, req)

    class Https(urllib.request.HTTPSHandler):
        """HTTPS over peer-checked connections."""

        def https_open(self, req):
            """Open over a connection that vets its peer."""
            conn = _peer_checked(http.client.HTTPSConnection, policy, _proxied(req))
            return self.do_open(conn, req, context=self._context)  # pylint: disable=protected-access

    return urllib.request.build_opener(_Redirects(policy), Http, Https)


def _read_capped(resp, max_bytes: int) -> bytes:
    announced = resp.headers.get("Content-Length")
    if announced and announced.isdigit() and int(announced) > max_bytes:
        raise NeedsClarificationError(f"response larger than max_fetch_bytes ({max_bytes})")
    body = resp.read(max_bytes + 1)  # never buffers more than cap+1
    if len(body) > max_bytes:
        raise NeedsClarificationError(f"response larger than max_fetch_bytes ({max_bytes})")
    return body


def fetch(url: str, *, max_bytes: int, timeout: float | None = None,
          untrusted: bool = False) -> FetchResult:
    """GET url (http/https only); the body is capped at max_bytes.

    untrusted (imported chat content): public addresses only. Otherwise a private target is
    allowed only when the submitted URL itself is private. Every redirect hop and the connected
    peer are re-checked, so a public host can never bounce the fetch into private space.
    """
    if urlparse(url).scheme not in ("http", "https"):
        raise ValueError(f"unsupported URL scheme: {url!r} (only http/https)")
    allow_private = not untrusted and netguard.private_target(url)
    netguard.check_url(url, allow_private=allow_private)
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "*/*"})
    opener = _opener(_Policy(allow_private))
    try:
        resp = opener.open(req, timeout=timeout or FETCH_TIMEOUT)
    except urllib.error.HTTPError as e:  # non-2xx: still hand back status + capped body
        if 300 <= e.code < 400:  # unfollowed redirect (disallowed scheme or loop)
            raise RuntimeError(
                f"redirect refused (HTTP {e.code}) from {url}: {e.headers.get('Location')}"
            ) from e
        with e:
            return FetchResult(
                e.code, e.headers.get("Content-Type", ""), _read_capped(e, max_bytes), url
            )
    with resp:
        return FetchResult(
            resp.status,
            resp.headers.get("Content-Type", ""),
            _read_capped(resp, max_bytes),
            resp.geturl(),
        )


def _decode(res: FetchResult) -> str:
    m = re.search(r"charset=([\w-]+)", res.content_type)
    try:
        return res.body.decode(m.group(1) if m else "utf-8", errors="replace")
    except LookupError:
        return res.body.decode("utf-8", errors="replace")


def _reddit(url: str, ctx: ExtractCtx) -> Extracted:
    p = urlparse(url)
    jurl = urlunparse(p._replace(path=p.path.rstrip("/") + ".json", query="", fragment=""))
    res = fetch(jurl, max_bytes=ctx.cfg.max_fetch_bytes, untrusted=netguard.untrusted(ctx.row))
    _check_status(res)
    data = json.loads(_decode(res))
    post = data[0]["data"]["children"][0]["data"]
    comments = [
        c["data"]
        for c in data[1]["data"]["children"]
        if c.get("kind", "t1") == "t1" and c["data"].get("body")
    ]
    comments.sort(key=lambda c: c.get("score", 0), reverse=True)
    title = post.get("title", "")
    sections = [("post", f"# {title}\n\n{post.get('selftext', '')}".strip())]
    sections += [(f"comment={i}", c["body"].strip()) for i, c in enumerate(comments[:10], 1)]
    return Extracted(
        title,
        post.get("author"),
        url,
        "web",
        "\n\n".join(t for _, t in sections),
        sections=sections,
        metadata={"subreddit": post.get("subreddit")},
        original_sha=ctx.blobs.put_bytes(res.body),
    )


def _check_status(res: FetchResult) -> None:
    if res.status in (401, 402, 403, 451):
        raise NeedsClarificationError(f"HTTP {res.status}: {PASTE}", pasteable=True)
    if res.status >= 400:
        raise RuntimeError(f"HTTP {res.status} fetching {res.final_url}")


@register("web")
def extract(ctx: ExtractCtx) -> Extracted:
    """Fetch the URL exactly as submitted; cite the URL that actually served the content.

    canonical_url is only the dedupe key and is never fetched or shown.
    """
    url = (ctx.row["payload_text"] or "").strip() or ctx.row["canonical_url"]
    if not url:
        raise NeedsClarificationError("web item has no URL")
    p = urlparse(url)
    host = (p.hostname or "").lower()
    if _REDDIT_PATH.match(p.path) and any(
        host == h or host.endswith("." + h) for h in REDDIT_HOSTS
    ):
        return _reddit(url, ctx)
    res = fetch(url, max_bytes=ctx.cfg.max_fetch_bytes, untrusted=netguard.untrusted(ctx.row))
    _check_status(res)
    ct = res.content_type.split(";")[0].strip().lower()
    if ct == "application/pdf":
        raise NeedsClarificationError("URL serves a PDF; download it and submit the file")
    if ct and not (ct.startswith("text/") or ct in ("application/xhtml+xml", "application/xml")):
        raise NeedsClarificationError(
            f"URL serves {ct}, not a web page; download it and submit the file instead"
        )
    sha = ctx.blobs.put_bytes(res.body)
    html = _decode(res)
    title, text, links, meta = extract_main(html, res.final_url)
    # wall markers only count on short pages: a long tutorial may say "enable JavaScript"
    if len(text) < 200 or (len(text) < 1500 and _WALL.search(text)):
        raise NeedsClarificationError(PASTE, pasteable=True)
    return Extracted(
        title or res.final_url,
        meta.get("author"),
        res.final_url,
        "web",
        text,
        metadata={**meta, "links": links[:200]},
        original_sha=sha,
    )
