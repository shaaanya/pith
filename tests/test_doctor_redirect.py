"""doctor probes never follow a redirect, so the key header never reaches a second host."""

import http.server
import threading

import pytest

from pith import doctor
from pith.config import Config

KEY = "dummy-key-not-real"


class _Recorder(http.server.BaseHTTPRequestHandler):
    """Records (method, path, Authorization) and answers with the server's canned reply."""

    def _serve(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n:
            self.rfile.read(n)
        self.server.seen.append((self.command, self.path, self.headers.get("Authorization")))
        code, location = self.server.reply(self.path)
        self.send_response(code)
        if location:
            self.send_header("Location", location)
        body = b"{}"
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = do_POST = _serve  # noqa: N815 - http.server naming

    def log_message(self, *_args):  # silence stderr
        """No logging."""


class _Server:
    """Loopback HTTP server on an ephemeral port."""

    def __init__(self, reply):
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Recorder)
        self.httpd.seen, self.httpd.reply = [], reply
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.05},
                         daemon=True).start()

    @property
    def seen(self):
        """Requests received so far."""
        return self.httpd.seen

    def stop(self):
        """Shut the server down."""
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture(name="target")
def _target():
    srv = _Server(lambda _p: (200, None))
    yield srv
    srv.stop()


def _check(tmp_path, base_url, monkeypatch, embed=True):
    monkeypatch.setenv("DUMMY_KEY_ENV", KEY)
    home = tmp_path / "home"
    be = {"type": "openai_compat", "base_url": base_url, "model": "m",
          "api_key_env": "DUMMY_KEY_ENV"}
    if embed:
        be["embed_model"] = "e"
    cfg = Config(home=home, db_path=home / "infoparser.db", blobs_dir=home / "blobs",
                 vault_dir=home / "vault", backends={"l": be}, tasks={}, allow_remote=False)
    return next(c for c in doctor.run(cfg) if c.name == "backend:l")


def _dest(kind, target):
    return {"loopback": f"http://127.0.0.1:{target.port}/v1/models",
            "localhost-undeclared": f"http://localhost:{target.port}/v1/models",
            "lan": "http://192.168.1.50:9/v1/models",
            "remote": "http://remote.invalid/v1/models"}[kind]


@pytest.mark.parametrize("code", [301, 302, 307])
@pytest.mark.parametrize("kind", ["loopback", "localhost-undeclared", "lan", "remote"])
def test_models_probe_redirect_is_a_failure_and_never_followed(
        tmp_path, monkeypatch, target, code, kind):
    """A 30x on the probe is reported, the second host gets nothing, the key stays on the first."""
    origin = _Server(lambda _p: (code, _dest(kind, target)))
    try:
        c = _check(tmp_path, f"http://127.0.0.1:{origin.port}/v1", monkeypatch)
    finally:
        origin.stop()
    assert c.level == "WARN" and "redirect" in c.detail.lower()
    assert target.seen == []
    assert origin.seen and all(a == f"Bearer {KEY}" for _m, _p, a in origin.seen)
    assert KEY not in c.detail


@pytest.mark.parametrize("code", [301, 302, 307])
def test_embeddings_probe_redirect_is_a_failure_and_never_followed(
        tmp_path, monkeypatch, target, code):
    """Same for the POST /embeddings probe (a 307 would otherwise replay the body and key)."""
    dest = f"http://127.0.0.1:{target.port}/v1/embeddings"
    origin = _Server(lambda p: (200, None) if p.endswith("/models") else (code, dest))
    try:
        c = _check(tmp_path, f"http://127.0.0.1:{origin.port}/v1", monkeypatch)
    finally:
        origin.stop()
    assert c.level == "WARN" and "redirect" in c.detail.lower()
    assert "/embeddings failed" in c.detail
    assert target.seen == []


def test_ordinary_local_backend_still_passes(tmp_path, monkeypatch):
    """No redirect: reachable, embeddings ok, key sent to that host only."""
    origin = _Server(lambda _p: (200, None))
    try:
        c = _check(tmp_path, f"http://127.0.0.1:{origin.port}/v1", monkeypatch)
    finally:
        origin.stop()
    assert c.level == "OK" and "reachable" in c.detail and "/embeddings ok" in c.detail
    assert {p for _m, p, _a in origin.seen} == {"/v1/models", "/v1/embeddings"}
