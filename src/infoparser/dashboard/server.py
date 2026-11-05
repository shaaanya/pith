"""Dashboard HTTP server: routing, auth and browser-security checks only. All logic is in dashboard.api.

Security model (loopback, single user):
- Token required for /api/*: `X-Token`/Bearer header (scripts) or the HttpOnly SameSite=Strict `ip_token` cookie
  (browser; set by opening `/?token=...` once, which redirects to `/`).
- Host header must be a loopback name + our port (or the explicit bind host): defeats DNS rebinding.
- Cookie-authenticated requests that change state must carry an Origin equal to the Host (CSRF). No CORS headers.
- CSP default-src 'none' with a per-response nonce for the one inline script/style; no external hosts at all.
- The dashboard shares the local ingest token (<home>/http_token) on purpose: one secret per home.
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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from urllib.parse import parse_qs, quote, unquote, urlsplit

from infoparser.inbox.ingest import LOOPBACK, load_token, parse_multipart
from infoparser.dashboard import api
from infoparser.inbox.service import Inbox
from infoparser.jobs import JobQueue
from infoparser.store.db import connect

MAX_JSON = 1_000_000
_ID = r"([0-9A-Za-z]{1,64})"
_LOOP_NAMES = {"127.0.0.1", "localhost", "::1"}


def _index_html() -> str:
    return resources.files("infoparser.dashboard").joinpath("static/index.html").read_text(encoding="utf-8")


class _Handler(BaseHTTPRequestHandler):
    server_version = "InfoParser"
    protocol_version = "HTTP/1.1"
    timeout = 30

    def log_message(self, *a):
        pass

    # ---- output
    def _headers(self, nonce: str | None = None) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        if nonce:
            self.send_header("Content-Security-Policy", (
                f"default-src 'none'; script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; connect-src 'self'; "
                "img-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"))
        else:
            self.send_header("Content-Security-Policy", "default-src 'none'; sandbox")

    def _send(self, status: int, data: bytes, ctype: str, *, nonce=None, extra=(), close=False) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self._headers(nonce)
        for k, v in extra:
            self.send_header(k, v)
        if close or status in (400, 401, 403, 411, 413):
            self.send_header("Connection", "close")
            self.close_connection = True
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
            if not self._host_ok():
                return self._err(403, "bad Host header")
            parts = urlsplit(self.path)
            path, q = parts.path, {k: v[0] for k, v in parse_qs(parts.query).items()}
            if self.command in ("GET", "HEAD") and path in ("/", "/index.html"):
                return self._index(q)
            if self.command in ("GET", "HEAD") and path == "/favicon.ico":
                return self._send(204, b"", "image/x-icon")
            if not path.startswith("/api/"):
                return self._err(404, "not found")
            how = self._auth()
            if how is None:
                return self._err(401, "unauthorized: open the URL printed by `infoparser run`")
            if self.command not in ("GET", "HEAD") and how == "cookie" and not self._origin_ok():
                return self._err(403, "bad Origin")
            self._route(path, q)
        except ValueError as e:
            self._err(400, str(e))
        except KeyError:
            self._err(404, "not found")
        except Exception as e:  # noqa: BLE001 - never leak a traceback to the client
            print(f"dashboard: {self.command} {self.path}: {type(e).__name__}: {e}", file=sys.stderr)
            self._err(500, "internal error")

    do_GET = do_POST = do_PATCH = do_DELETE = do_HEAD = _handle

    def _405(self) -> None:
        self._err(405, "method not allowed")

    do_PUT = do_OPTIONS = _405

    def _index(self, q: dict) -> None:
        tok = q.get("token")
        if tok is not None:
            if not hmac.compare_digest(tok.encode(), self.server.token.encode()):
                return self._err(403, "bad token")
            return self._send(302, b"", "text/plain", extra=[
                ("Location", "/"),
                ("Set-Cookie", f"ip_token={quote(tok, safe='')}; HttpOnly; SameSite=Strict; Path=/; Max-Age=604800")])
        nonce = secrets.token_urlsafe(16)
        self._send(200, self.server.index.replace("{{nonce}}", nonce).encode(), "text/html; charset=utf-8", nonce=nonce)

    def _body(self, *, cap: int | None = None) -> bytes:
        n = self.headers.get("Content-Length")
        if n is None or not n.isdigit():
            raise _Reject(411, "Content-Length required")
        if int(n) > (cap or MAX_JSON):
            raise _Reject(413, "body too large")
        return self.rfile.read(int(n))

    def _json_body(self):
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
            svc = dataclasses.replace(s, conn=c, inbox=Inbox(c, s.blobs, s.cfg), queue=JobQueue(c, s.cfg))
            self._dispatch(svc, path, q)
        except _Reject as r:
            self._err(r.status, r.msg)
        finally:
            c.close()

    def _dispatch(self, svc, path: str, q: dict) -> None:
        m, J = self.command, self._json
        if m == "HEAD":
            m = "GET"
        if path == "/api/inbox":
            if m == "GET":
                return J(200, api.inbox_list(svc, q.get("status")))
            if m == "POST":
                return J(200, api.inbox_submit(svc, self._submission()))
        elif x := re.fullmatch(rf"/api/inbox/{_ID}", path):
            if m == "GET":
                return J(200, api.inbox_get(svc, x[1]))
        elif x := re.fullmatch(rf"/api/inbox/{_ID}/retry", path):
            if m == "POST":
                self._json_body()
                return J(200, api.retry(svc, x[1]))
        elif x := re.fullmatch(rf"/api/inbox/{_ID}/clarify", path):
            if m == "POST":
                body = self._json_body()
                return J(200, api.clarify(svc, x[1], body.get("text") if isinstance(body, dict) else None))
        elif path == "/api/search" and m == "GET":
            return J(200, api.search(svc, q.get("q", ""), {k: q.get(k) for k in ("kind", "topic", "provenance")}))
        elif path == "/api/ask" and m == "POST":
            body = self._json_body()
            return J(200, api.ask(svc, body.get("q") if isinstance(body, dict) else None))
        elif x := re.fullmatch(rf"/api/items/{_ID}", path):
            if m == "GET":
                return J(200, api.item_detail(svc, x[1]))
            if m == "PATCH":
                return J(200, api.item_update(svc, x[1], self._json_body()))
            if m == "DELETE":
                return J(200, api.item_delete(svc, x[1]))
        elif x := re.fullmatch(rf"/api/items/{_ID}/reprocess", path):
            if m == "POST":
                self._json_body()
                return J(200, api.item_reprocess(svc, x[1]))
        elif path in ("/api/topics", "/api/duplicates", "/api/digest", "/api/privacy", "/api/state") and m == "GET":
            return J(200, getattr(api, path[5:])(svc))
        elif x := re.fullmatch(r"/api/blob/([^/]+)", path):
            if m == "GET":
                return self._blob(svc, unquote(x[1]))
        else:
            return self._err(404, "not found")
        self._err(405, "method not allowed")

    def _submission(self) -> dict:
        ctype = self.headers.get("Content-Type", "")
        base = ctype.split(";")[0].strip().lower()
        if base in ("application/json", ""):
            body = self._json_body()
            if isinstance(body, dict) and ("file" in body or "filename" in body):
                raise ValueError("file upload requires raw or multipart body")
            return body
        raw = self._body(cap=self.server.services.cfg.max_fetch_bytes)
        if base == "multipart/form-data":
            return parse_multipart(ctype, raw)
        if not raw:
            raise ValueError("empty body")
        return {"file": raw, "filename": self.headers.get("X-Filename"), "context": self.headers.get("X-Context")}

    def _blob(self, svc, sha: str) -> None:
        path, ctype, inline = api.blob(svc, sha)
        size = path.stat().st_size
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(size))
        self.send_header("Content-Disposition", f'{"inline" if inline else "attachment"}; filename="{sha[:16]}"')
        self._headers()
        self.end_headers()
        if self.command == "HEAD":
            return
        with open(path, "rb") as f:
            while chunk := f.read(65536):
                self.wfile.write(chunk)


class _Reject(Exception):
    def __init__(self, status: int, msg: str):
        self.status, self.msg = status, msg


class DashboardServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, services, host: str, port: int, token: str):
        self.services, self.token, self.bind_host, self.index = services, token, host, _index_html()
        super().__init__((host, port), _Handler)


def make_server(services, host: str = "127.0.0.1", port: int = 8777, token: str | None = None) -> DashboardServer:
    if host not in LOOPBACK and not token:
        raise ValueError("dashboard binds loopback only; a non-loopback host requires an explicit token")
    return DashboardServer(services, host, port, token or load_token(services.cfg))
