"""Dashboard HTTP server: routing, auth and browser-security checks only. All logic is in
dashboard.api.

Security model (loopback, single user):
- Token required for /api/*: `X-Token`/Bearer header (scripts) or the HttpOnly SameSite=Strict
  `ip_token` cookie (browser; set by opening `/?token=...` once, which redirects to `/`).
- Host header must be a loopback name + our port (or the explicit bind host): defeats DNS rebinding.
- Cookie-authenticated requests that change state must carry an Origin equal to the Host (CSRF).
  No CORS headers.
- CSP default-src 'none' with a per-response nonce for the one inline script/style; no external
  hosts at all.
- The dashboard shares the local ingest token (<home>/http_token) on purpose: one secret per
  home.
- Non-loopback bind is refused unless an explicit token is passed.
- Every request opens its own SQLite connection; errors are JSON {error}, never tracebacks.
"""
from __future__ import annotations

import dataclasses
import hmac
import json
import re
import secrets
import sys
from http.server import ThreadingHTTPServer
from importlib import resources
from urllib.parse import parse_qs, quote, unquote, urlsplit

from pith import settings
from pith.dashboard import api
from pith.inbox.ingest import LOOPBACK, QuietHandler, load_token
from pith.inbox.service import Inbox
from pith.jobs import JobQueue
from pith.providers.registry import Registry
from pith.store.db import connect

MAX_JSON = 1_000_000
_ID = r"([0-9A-Za-z]{1,64})"
_SHELF = r"([0-9a-z-]{1,64})"
_LOOP_NAMES = {"127.0.0.1", "localhost", "::1"}


def _index_html() -> str:
    """The single-page UI source."""
    page = resources.files("pith.dashboard").joinpath("static/index.html")
    return page.read_text(encoding="utf-8")


class _Handler(QuietHandler):
    """Routing, auth and browser-security checks; the logic lives in dashboard.api."""

    # ---- output
    def _headers(self, nonce: str | None = None) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        if nonce:
            self.send_header("Content-Security-Policy", (
                f"default-src 'none'; script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; "
                "connect-src 'self'; img-src 'self'; base-uri 'none'; form-action 'none'; "
                "frame-ancestors 'none'"))
        else:
            self.send_header("Content-Security-Policy", "default-src 'none'; sandbox")

    def _send(self, status: int, data: bytes, ctype: str, *,  # pylint: disable=too-many-arguments  # status/body/type + header options
              nonce=None, extra=(), close=False) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self._headers(nonce)
        for k, v in extra:
            self.send_header(k, v)
        if close or status in (400, 401, 403, 411, 413):
            self.send_header("Connection", "close")
            self.close_connection = True  # pylint: disable=attribute-defined-outside-init  # stdlib handler flag
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _json(self, status: int, obj) -> None:
        self._send(status, json.dumps(obj).encode(), "application/json")

    def _err(self, status: int, msg: str) -> None:
        self._json(status, {"error": msg})

    # ---- checks
    def _host_ok(self) -> bool:
        host = self.headers.get("Host") or ""
        try:
            u = urlsplit("//" + host)
            name, port = (u.hostname or "").lower(), u.port
        except ValueError:
            return False
        allowed = _LOOP_NAMES | {self.server.bind_host.lower()}
        return name in allowed and port == self.server.server_address[1]

    def _auth(self) -> str | None:
        """'header' | 'cookie' | None"""
        tok = self.server.token.encode()
        got = self.headers.get("X-Token") or ""
        auth = self.headers.get("Authorization") or ""
        if auth.startswith("Bearer "):
            got = auth[7:]
        if got and hmac.compare_digest(got.encode(), tok):
            return "header"
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == "ip_token" and v and hmac.compare_digest(unquote(v).encode(), tok):
                return "cookie"
        return None

    def _origin_ok(self) -> bool:
        origin = self.headers.get("Origin")
        return origin is not None and origin == f"http://{self.headers.get('Host')}"

    # ---- dispatch
    def _handle(self) -> None:
        try:
            self._handle_checked()
        except ValueError as e:
            self._err(400, str(e))
        except KeyError:
            self._err(404, "not found")
        except Exception as e:  # noqa: BLE001  # pylint: disable=broad-exception-caught
            # never leak a traceback to the client
            print(f"dashboard: {self.command} {self.path}: {type(e).__name__}: {e}",
                  file=sys.stderr)
            self._err(500, "internal error")

    def _handle_checked(self) -> None:
        if not self._host_ok():
            self._err(403, "bad Host header")
            return
        parts = urlsplit(self.path)
        path, q = parts.path, {k: v[0] for k, v in parse_qs(parts.query).items()}
        if self.command in ("GET", "HEAD") and path in ("/", "/index.html"):
            self._index(q)
        elif self.command in ("GET", "HEAD") and path == "/favicon.ico":
            self._send(204, b"", "image/x-icon")
        elif not path.startswith("/api/"):
            self._err(404, "not found")
        else:
            self._api(path, q)

    def _api(self, path: str, q: dict) -> None:
        how = self._auth()
        if how is None:
            self._err(401, "unauthorized: open the URL printed by `pith run`")
        elif self.command not in ("GET", "HEAD") and how == "cookie" and not self._origin_ok():
            self._err(403, "bad Origin")
        else:
            self._route(path, q)

    do_GET = do_POST = do_PATCH = do_DELETE = do_HEAD = _handle

    def _405(self) -> None:
        self._err(405, "method not allowed")

    do_PUT = do_OPTIONS = _405

    def _index(self, q: dict) -> None:
        tok = q.get("token")
        if tok is not None:
            if not hmac.compare_digest(tok.encode(), self.server.token.encode()):
                self._err(403, "bad token")
                return
            cookie = (f"ip_token={quote(tok, safe='')}; HttpOnly; SameSite=Strict; Path=/; "
                      "Max-Age=604800")
            self._send(302, b"", "text/plain", extra=[("Location", "/"), ("Set-Cookie", cookie)])
            return
        nonce = secrets.token_urlsafe(16)
        page = self.server.index.replace("{{nonce}}", nonce).encode()
        self._send(200, page, "text/html; charset=utf-8", nonce=nonce)

    def _body(self, *, cap: int | None = None) -> bytes:
        n = self.headers.get("Content-Length")
        if n is None or not n.isdigit():
            raise _Reject(411, "Content-Length required")
        if int(n) > (cap or MAX_JSON):
            raise _Reject(413, "body too large")
        return self.rfile.read(int(n))

    def json_body(self):
        """The request body as JSON ({} when empty); ValueError if malformed."""
        raw = self._body()
        if not raw.strip():
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except ValueError as e:
            raise ValueError("malformed JSON") from e

    def _route(self, path: str, q: dict) -> None:
        s = self.server.services
        c = connect(s.cfg.db_path)
        try:
            svc = dataclasses.replace(s, conn=c, inbox=Inbox(c, s.blobs, s.cfg),
                                      queue=JobQueue(c, s.cfg))
            self._dispatch(svc, path, q)
        except _Reject as r:
            self._err(r.status, r.msg)
        finally:
            c.close()

    def _dispatch(self, svc, path: str, q: dict) -> None:
        method = "GET" if self.command == "HEAD" else self.command
        for pattern, handlers, strict in _ROUTES:
            x = re.fullmatch(pattern, path)
            if not x:
                continue
            if fn := handlers.get(method):
                out = fn(self, svc, x, q)
                if out is not RESPONDED:
                    self._json(200, out)
                return
            if strict:  # a known resource with an unsupported method
                self._err(405, "method not allowed")
                return
        self._err(404, "not found")

    def submission(self) -> dict:
        """The submission dict from the JSON, multipart or raw upload body."""
        ctype = self.headers.get("Content-Type", "")
        base = ctype.split(";")[0].strip().lower()
        if base in ("application/json", ""):
            body = self.json_body()
            if isinstance(body, dict) and ("file" in body or "filename" in body):
                raise ValueError("file upload requires raw or multipart body")
            return body
        raw = self._body(cap=self.server.services.cfg.max_fetch_bytes)
        return self.upload_body(ctype, raw)

    def send_blob(self, svc, sha: str) -> None:
        """Stream a stored blob (inline only for safe image types)."""
        path, ctype, inline = api.blob(svc, sha)
        size = path.stat().st_size
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(size))
        disposition = "inline" if inline else "attachment"
        self.send_header("Content-Disposition", f'{disposition}; filename="{sha[:16]}"')
        self._headers()
        self.end_headers()
        if self.command == "HEAD":
            return
        with path.open("rb") as f:
            while chunk := f.read(65536):
                self.wfile.write(chunk)


class _Reject(Exception):
    """An early, expected HTTP error (status + message), not a failure."""

    def __init__(self, status: int, msg: str):
        self.status, self.msg = status, msg


def _inbox_item(_h, svc, x, _q):
    return api.inbox_get(svc, x[1])


def _retry(h, svc, x, _q):
    h.json_body()
    return api.retry(svc, x[1])


def _clarify(h, svc, x, _q):
    body = h.json_body()
    return api.clarify(svc, x[1], body.get("text") if isinstance(body, dict) else None)


def _ask(h, svc, _x, _q):
    body = h.json_body()
    return api.ask(svc, body.get("q") if isinstance(body, dict) else None)


def _reprocess(h, svc, x, _q):
    h.json_body()
    return api.item_reprocess(svc, x[1])


def _viewed(h, svc, x, _q):
    h.json_body()  # drain the request body so the connection stays in sync
    return api.item_viewed(svc, x[1])


def _note(h, svc, x, _q):
    return api.item_note(svc, x[1], h.json_body())


def _config_save(h, svc, _x, _q):
    new = settings.save(svc.cfg, h.json_body())
    h.server.apply_config(new)
    return settings.view(new)


RESPONDED = object()  # sentinel: the handler already sent its own response


def _blob(h, svc, x, _q):
    h.send_blob(svc, unquote(x[1]))
    return RESPONDED


# (path regex, {method: handler(h, svc, match, query)}, 405 vs 404 for an unsupported method).
# A handler returns the JSON body (None is JSON null), or RESPONDED once it wrote the response.
_ROUTES = (
    ("/api/inbox", {"GET": lambda h, s, x, q: api.inbox_list(s, q.get("status")),
                    "POST": lambda h, s, x, q: api.inbox_submit(s, h.submission())}, True),
    (rf"/api/inbox/{_ID}", {"GET": _inbox_item}, True),
    (rf"/api/inbox/{_ID}/retry", {"POST": _retry}, True),
    (rf"/api/inbox/{_ID}/clarify", {"POST": _clarify}, True),
    ("/api/search", {"GET": lambda h, s, x, q: api.search(
        s, q.get("q", ""), {k: q.get(k) for k in ("kind", "topic", "provenance")})}, False),
    ("/api/library", {"GET": lambda h, s, x, q: api.library(
        s, q, int(q["limit"]) if q.get("limit", "").isdigit() else 40)}, False),
    ("/api/ask", {"POST": _ask}, False),
    ("/api/shelves", {"GET": lambda h, s, x, q: api.shelves(s),
                      "POST": lambda h, s, x, q: api.shelf_create(s, h.json_body())}, True),
    (rf"/api/shelves/{_SHELF}", {"PATCH": lambda h, s, x, q: api.shelf_update(s, x[1], h.json_body()),
                                 "DELETE": lambda h, s, x, q: api.shelf_delete(s, x[1])}, True),
    (rf"/api/items/{_ID}", {"GET": lambda h, s, x, q: api.item_detail(s, x[1]),
                            "PATCH": lambda h, s, x, q: api.item_update(s, x[1], h.json_body()),
                            "DELETE": lambda h, s, x, q: api.item_delete(s, x[1])}, True),
    (rf"/api/items/{_ID}/reprocess", {"POST": _reprocess}, True),
    (rf"/api/items/{_ID}/note", {"POST": _note}, True),
    (rf"/api/items/{_ID}/viewed", {"POST": _viewed}, True),
    ("/api/resurface", {"GET": lambda h, s, x, q: api.resurface(s)}, False),
    ("/api/entries", {"GET": lambda h, s, x, q: api.entries(s, q)}, False),
    (rf"/api/entries/{_ID}", {"PATCH": lambda h, s, x, q: api.entry_update(s, x[1], h.json_body())},
     True),
    ("/api/(topics|duplicates|digest|privacy|state)",
     {"GET": lambda h, s, x, q: getattr(api, x[1])(s)}, False),
    ("/api/blob/([^/]+)", {"GET": _blob}, True),
    ("/api/config", {"GET": lambda h, s, x, q: settings.view(s.cfg), "POST": _config_save}, True),
    ("/api/providers/detect", {"GET": lambda h, s, x, q: {"providers": settings.detect()}}, True),
    ("/api/models", {"GET": lambda h, s, x, q: {"models": settings.list_models(q.get("base_url"))}},
     True),
)


class DashboardServer(ThreadingHTTPServer):
    """Threaded server carrying the services, token, bind host and the index page."""

    daemon_threads = True

    def __init__(self, services, host: str, port: int, token: str):
        self.services, self.token, self.bind_host, self.index = services, token, host, _index_html()
        self.listeners = []  # called with the new Registry after a settings save
        super().__init__((host, port), _Handler)

    def apply_config(self, new) -> None:
        """Make a saved (already validated) config live: backends, task routing, allow_remote.
        In-flight calls finish on the old registry; the next call uses the new one."""
        reg = Registry.from_config(new)
        cfg = self.services.cfg
        cfg.backends, cfg.tasks, cfg.allow_remote, cfg.source = (
            new.backends, new.tasks, new.allow_remote, new.source)
        self.services.registry = reg
        for fn in self.listeners:
            fn(reg)


def make_server(services, host: str = "127.0.0.1", port: int = 8777,
                token: str | None = None) -> DashboardServer:
    """Build the server; a non-loopback host needs an explicit token."""
    if host not in LOOPBACK and not token:
        raise ValueError(
            "dashboard binds loopback only; a non-loopback host requires an explicit token")
    return DashboardServer(services, host, port, token or load_token(services.cfg))
