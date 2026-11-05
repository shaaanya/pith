from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlparse, urlunparse

from infoparser.pipeline.extractors.base import Extracted, ExtractCtx, NeedsClarificationError, register
from infoparser.pipeline.htmltext import extract_main

FETCH_TIMEOUT = 20  # seconds; module-level so tests can shorten it
_UA = "Mozilla/5.0 (compatible; InfoParser/0.1; +local personal knowledge tool)"
_WALL = re.compile(r"log ?in to (continue|read|view)|sign ?in to (continue|read|view)|subscribe to (continue|read)|"
                   r"subscribers only|create (a free )?account to (continue|read)|enable javascript|"
                   r"verify you are (a )?human", re.I)
_REDDIT_PATH = re.compile(r"^/r/[^/]+/comments/")
PASTE = "login or paywall; paste the text"
# ponytail: private-IP/SSRF blocking not done (user's own machine, local fixture server needs localhost)


@dataclass
class FetchResult:
    status: int
    content_type: str
    body: bytes
    final_url: str


class _Redirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlparse(newurl).scheme not in ("http", "https"):
            raise urllib.error.URLError(f"refusing redirect to non-http(s) scheme: {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _read_capped(resp, max_bytes: int) -> bytes:
    announced = resp.headers.get("Content-Length")
    if announced and announced.isdigit() and int(announced) > max_bytes:
        raise NeedsClarificationError(f"response larger than max_fetch_bytes ({max_bytes})")
    body = resp.read(max_bytes + 1)  # never buffers more than cap+1
    if len(body) > max_bytes:
        raise NeedsClarificationError(f"response larger than max_fetch_bytes ({max_bytes})")
    return body


def fetch(url: str, *, max_bytes: int, timeout: float | None = None) -> FetchResult:
    if urlparse(url).scheme not in ("http", "https"):
        raise ValueError(f"unsupported URL scheme: {url!r} (only http/https)")
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "*/*"})
    opener = urllib.request.build_opener(_Redirects)
    try:
        resp = opener.open(req, timeout=timeout or FETCH_TIMEOUT)
    except urllib.error.HTTPError as e:  # non-2xx: still hand back status + capped body
        if 300 <= e.code < 400:  # unfollowed redirect (disallowed scheme or loop)
            raise RuntimeError(f"redirect refused (HTTP {e.code}) from {url}: {e.headers.get('Location')}") from e
        with e:
            return FetchResult(e.code, e.headers.get("Content-Type", ""), _read_capped(e, max_bytes), url)
    with resp:
        return FetchResult(resp.status, resp.headers.get("Content-Type", ""), _read_capped(resp, max_bytes),
                           resp.geturl())


def _decode(res: FetchResult) -> str:
    m = re.search(r"charset=([\w-]+)", res.content_type)
    try:
        return res.body.decode(m.group(1) if m else "utf-8", errors="replace")
    except LookupError:
        return res.body.decode("utf-8", errors="replace")


def _reddit(url: str, ctx: ExtractCtx) -> Extracted:
    p = urlparse(url)
    jurl = urlunparse(p._replace(path=p.path.rstrip("/") + ".json", query="", fragment=""))
    res = _fetch_with_http_fallback(jurl, ctx, raw_url=ctx.row["payload_text"])
    _check_status(res)
    data = json.loads(_decode(res))
    post = data[0]["data"]["children"][0]["data"]
    comments = [c["data"] for c in data[1]["data"]["children"] if c.get("kind", "t1") == "t1" and c["data"].get("body")]
    comments.sort(key=lambda c: c.get("score", 0), reverse=True)
    title = post.get("title", "")
    sections = [("post", f"# {title}\n\n{post.get('selftext', '')}".strip())]
    sections += [(f"comment={i}", c["body"].strip()) for i, c in enumerate(comments[:10], 1)]
    return Extracted(title, post.get("author"), url, "web", "\n\n".join(t for _, t in sections),
                     sections=sections, metadata={"subreddit": post.get("subreddit")},
                     original_sha=ctx.blobs.put_bytes(res.body))


def _check_status(res: FetchResult) -> None:
    if res.status in (401, 402, 403, 451):
        raise NeedsClarificationError(f"HTTP {res.status}: {PASTE}")
    if res.status >= 400:
        raise RuntimeError(f"HTTP {res.status} fetching {res.final_url}")


def _fetch_with_http_fallback(url: str, ctx: ExtractCtx, raw_url: str | None = None) -> FetchResult:
    """canonical_url is always https; if that connection fails, retry the URL exactly as submitted."""
    try:
        return fetch(url, max_bytes=ctx.cfg.max_fetch_bytes)
    except urllib.error.URLError:
        raw = (raw_url or ctx.row["payload_text"] or "").strip()
        if raw.startswith("http://") and urlparse(raw).netloc == urlparse(url).netloc:
            if raw_url:  # reddit: re-derive the .json URL from the http form
                q = urlparse(raw)
                raw = urlunparse(q._replace(path=q.path.rstrip("/") + ".json", query="", fragment=""))
            return fetch(raw, max_bytes=ctx.cfg.max_fetch_bytes)
        raise


@register("web")
def extract(ctx: ExtractCtx) -> Extracted:
    url = ctx.row["canonical_url"]
    if not url:
        raise NeedsClarificationError("web item has no URL")
    p = urlparse(url)
    if _REDDIT_PATH.match(p.path):
        return _reddit(url, ctx)
    res = _fetch_with_http_fallback(url, ctx)
    _check_status(res)
    sha = ctx.blobs.put_bytes(res.body)
    html = _decode(res)
    title, text, links, meta = extract_main(html, res.final_url)
    if len(text) < 200 or _WALL.search(text[:2000]):
        if len(text) < 200 or _WALL.search(text):
            raise NeedsClarificationError(PASTE)
    return Extracted(title or url, meta.get("author"), url, "web", text,
                     metadata={**meta, "links": links[:200]}, original_sha=sha)
