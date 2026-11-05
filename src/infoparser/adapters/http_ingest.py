"""Local HTTP ingest. Loopback by default; bearer/X-Token auth always required.

POST /v1/inbox  JSON {url|text, context?, platform?}  | multipart/form-data (file + optional
                fields) | raw body
                (file; name from X-Filename, context from X-Context)  -> {id, status, duplicate}
GET  /v1/inbox/<id> -> {id, status, error, content_type}
Token: cfg.http_token if set, else auto-generated into <home>/http_token (0600). Non-loopback bind
needs an explicit cfg.http_token. Each request opens its own SQLite connection. No CORS headers are
ever sent.
Client filenames are only metadata (sanitised); blobs are content-addressed.
"""
from __future__ import annotations

import hmac
import json
import re
from http.server import ThreadingHTTPServer

from infoparser.inbox.ingest import LOOPBACK, QuietHandler, handle, load_token
from infoparser.inbox.service import Inbox
from infoparser.store.blobs import BlobStore
from infoparser.store.db import connect, migrate

__all__ = ["IngestServer", "handle", "load_token"]  # handle/load_token: shared with the dashboard


class _Handler(QuietHandler):
    """Routes the ingest API; every request authenticates first."""

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
            self._send(401, {"error": "unauthorized"})
            return
        try:
            fn()
        except ValueError as e:
            self._send(400, {"error": str(e)})
        except Exception:  # noqa: BLE001  # pylint: disable=broad-exception-caught
            # never leak a traceback to the client
            self._send(500, {"error": "internal error"})

    def do_GET(self):  # pylint: disable=invalid-name  # http.server dispatch name
        """GET /v1/inbox/<id>."""
        self._guard(self._get)

    def do_POST(self):  # pylint: disable=invalid-name  # http.server dispatch name
        """POST /v1/inbox."""
        self._guard(self._post)

    def _405(self):
        n = self.headers.get("Content-Length")
        if n and n.isdigit():
            # drain so the unread body is not parsed as the next request
            self.rfile.read(min(int(n), 1 << 20))
        self.close_connection = True
        data = b'{"error": "method not allowed"}'
        self.send_response(405)
        self.send_header("Allow", "GET, POST")
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Connection", "close")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = _405

    def _get(self):
        m = re.fullmatch(r"/v1/inbox/([A-Za-z0-9]+)", self.path.split("?")[0])
        if not m:
            self._send(404, {"error": "not found"})
            return
        conn, inbox = self._inbox()
        try:
            try:
                r = inbox.get(m[1])
            except KeyError:
                self._send(404, {"error": "not found"})
                return
            self._send(200, {"id": r["id"], "status": r["status"], "error": r["error"],
                             "content_type": r["content_type"]})
        finally:
            conn.close()

    def _body(self, length: int) -> dict:
        """The submission dict from the JSON, multipart or raw request body (ValueError if bad)."""
        raw = self.rfile.read(length)
        ctype = self.headers.get("Content-Type", "")
        base = ctype.split(";")[0].strip().lower()
        if base == "application/json" or not ctype:
            try:
                body = json.loads(raw.decode("utf-8"))
            except ValueError as e:
                raise ValueError("malformed JSON") from e
            if isinstance(body, dict) and ("file" in body or "filename" in body):
                raise ValueError("file upload requires raw or multipart body")
            return body
        return self.upload_body(ctype, raw)

    def _post(self):
        if self.path.partition("?")[0] != "/v1/inbox":
            self._send(404, {"error": "not found"})
            return
        n = self.headers.get("Content-Length")
        if n is None or not n.isdigit():
            self._send(411, {"error": "Content-Length required"})
            return
        if int(n) > self.server.cfg.max_fetch_bytes:
            self._send(413, {"error": "body too large"})
            return
        body = self._body(int(n))
        conn, inbox = self._inbox()
        try:
            self._send(200, handle(inbox, body))
        finally:
            conn.close()


class IngestServer(ThreadingHTTPServer):
    """Threaded server carrying the config and the auth token."""

    daemon_threads = True

    def __init__(self, cfg, port: int | None = None):
        if cfg.http_bind not in LOOPBACK and not cfg.http_token:
            raise ValueError("non-loopback bind requires an explicit [http] token in config")
        self.cfg, self.token = cfg, load_token(cfg)
        super().__init__((cfg.http_bind, cfg.http_port if port is None else port), _Handler)
