"""Local HTTP ingest. Loopback by default; bearer/X-Token auth always required.

POST /v1/inbox  JSON {url|text, context?, platform?}  | multipart/form-data (file + optional fields) | raw body
                (file; name from X-Filename, context from X-Context)  -> {id, status, duplicate}
GET  /v1/inbox/<id> -> {id, status, error, content_type}
Token: cfg.http_token if set, else auto-generated into <home>/http_token (0600). Non-loopback bind needs an
explicit cfg.http_token. Each request opens its own SQLite connection. No CORS headers are ever sent.
Client filenames are only metadata (sanitised); blobs are content-addressed.
"""
from __future__ import annotations

import hmac
import json
import os
import re
import secrets
from email.parser import BytesParser
from email.policy import HTTP
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from infoparser.inbox.service import Inbox
from infoparser.store.blobs import BlobStore
from infoparser.store.db import connect, migrate

NAME = "http"
_HTTP_URL = re.compile(r"https?://\S+")
LOOPBACK = {"127.0.0.1", "::1", "localhost"}


def safe_filename(name: str | None) -> str | None:
    name = re.sub(r"[\x00-\x1f\x7f]", "", (name or "").replace("\\", "/")).split("/")[-1].strip().lstrip(".")
    return name[:200] or None


def handle(inbox: Inbox, body: dict) -> dict:
    """Validate and submit. ValueError -> caller answers 400."""
    if not isinstance(body, dict):
        raise ValueError("body must be a JSON object")
    url, text, ctx, plat, file = (body.get(k) for k in ("url", "text", "context", "platform", "file"))
    for k, v in (("url", url), ("text", text), ("context", ctx), ("platform", plat)):
        if v is not None and not isinstance(v, str):
            raise ValueError(f"{k} must be a string")
    if sum(bool(x) for x in (url, text, file)) != 1:
        raise ValueError("exactly one of url, text or file is required")
    if url and not _HTTP_URL.fullmatch(url.strip()):
        raise ValueError("url must be http(s)")
    kw = {"adapter": NAME, "user_context": ctx or None, "platform": plat or None}
    if file:
        r = inbox.submit(file=bytes(file), filename=safe_filename(body.get("filename")), **kw)
    else:
        r = inbox.submit(text=(url or text).strip(), **kw)
    status = inbox.get(r.id)["status"]
    return {"id": r.id, "status": status, "duplicate": r.duplicate_of is not None}


def load_token(cfg) -> str:
    if cfg.http_token:
        return cfg.http_token
    p = Path(cfg.home) / "http_token"
    if p.exists():
        tok = p.read_text().strip()
        if tok:
            if p.stat().st_mode & 0o077:
                p.chmod(0o600)
            return tok
    Path(cfg.home).mkdir(parents=True, exist_ok=True)
    tok = secrets.token_urlsafe(32)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(tok + "\n")
    return tok


def _parse_multipart(ctype: str, raw: bytes) -> dict:
    msg = BytesParser(policy=HTTP).parsebytes(b"Content-Type: " + ctype.encode() + b"\r\n\r\n" + raw)
    out: dict = {}
    for part in msg.iter_parts() if msg.is_multipart() else []:
        name = part.get_param("name", header="content-disposition")
        if not name:
            continue
        if part.get_filename() is not None:
            out["file"], out["filename"] = part.get_payload(decode=True) or b"", part.get_filename()
        else:
            out[name] = part.get_content()
    return out


class _Handler(BaseHTTPRequestHandler):
    server_version = "InfoParser"
    protocol_version = "HTTP/1.1"
    timeout = 30  # per-connection socket timeout: a slow-drip client cannot hold a thread forever

    def log_message(self, *a):  # quiet
        pass

    def _send(self, status: int, obj: dict) -> None:
        data = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        if status in (400, 401, 411, 413):
            self.send_header("Connection", "close")
            self.close_connection = True
        self.end_headers()
        self.wfile.write(data)

    def _authed(self) -> bool:
        got = self.headers.get("X-Token") or ""
        auth = self.headers.get("Authorization") or ""
        if auth.startswith("Bearer "):
            got = auth[7:]
        return hmac.compare_digest(got.encode(), self.server.token.encode())

    def _inbox(self):
        cfg = self.server.cfg
        conn = connect(cfg.db_path)
        migrate(conn)
        return conn, Inbox(conn, BlobStore(cfg.blobs_dir), cfg)

    def _guard(self, fn) -> None:
        if not self._authed():
            return self._send(401, {"error": "unauthorized"})
        try:
            fn()
        except ValueError as e:
            self._send(400, {"error": str(e)})
        except Exception:  # noqa: BLE001 - never leak a traceback
            self._send(500, {"error": "internal error"})

    def do_GET(self):
        self._guard(self._get)

    def do_POST(self):
        self._guard(self._post)

    def _405(self):
        data = b'{"error": "method not allowed"}'
        self.send_response(405)
        self.send_header("Allow", "GET, POST")
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = _405

    def _get(self):
        m = re.fullmatch(r"/v1/inbox/([A-Za-z0-9]+)", self.path.split("?")[0])
        if not m:
            return self._send(404, {"error": "not found"})
        conn, inbox = self._inbox()
        try:
            try:
                r = inbox.get(m[1])
            except KeyError:
                return self._send(404, {"error": "not found"})
            self._send(200, {"id": r["id"], "status": r["status"], "error": r["error"],
                             "content_type": r["content_type"]})
        finally:
            conn.close()

    def _post(self):
        path, _, query = self.path.partition("?")
        if path != "/v1/inbox":
            return self._send(404, {"error": "not found"})
        n = self.headers.get("Content-Length")
        if n is None or not n.isdigit():
            return self._send(411, {"error": "Content-Length required"})
        if int(n) > self.server.cfg.max_fetch_bytes:
            return self._send(413, {"error": "body too large"})
        raw = self.rfile.read(int(n))
        ctype = self.headers.get("Content-Type", "")
        base = ctype.split(";")[0].strip().lower()
        if base == "application/json" or not ctype:
            try:
                body = json.loads(raw.decode("utf-8"))
            except ValueError as e:
                raise ValueError("malformed JSON") from e
            if isinstance(body, dict) and ("file" in body or "filename" in body):
                raise ValueError("file upload requires raw or multipart body")
        elif base == "multipart/form-data":
            body = _parse_multipart(ctype, raw)
        else:
            body = {"file": raw, "filename": self.headers.get("X-Filename"), "context": self.headers.get("X-Context")}
            if not raw:
                raise ValueError("empty body")
        conn, inbox = self._inbox()
        try:
            self._send(200, handle(inbox, body))
        finally:
            conn.close()


class IngestServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, cfg, port: int | None = None):
        if cfg.http_bind not in LOOPBACK and not cfg.http_token:
            raise ValueError("non-loopback bind requires an explicit [http] token in config")
        self.cfg, self.token = cfg, load_token(cfg)
        super().__init__((cfg.http_bind, cfg.http_port if port is None else port), _Handler)
