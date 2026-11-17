"""Local backends never go through an environment proxy; remote ones keep the proxy behaviour."""
import http.server
import threading

import pytest
from stubs.anthropic_stub import AnthropicStub
from stubs.openai_stub import OpenAIStub

from pith import doctor
from pith.config import Config
from pith.providers.anthropic import AnthropicBackend
from pith.providers.registry import Registry

MSG = [{"role": "user", "content": "MY PRIVATE NOTE"}]


class _Proxy(http.server.BaseHTTPRequestHandler):
    """Fake forward proxy: records the request line, answers 502."""

    def do_POST(self):  # pylint: disable=invalid-name  # http.server dispatch name
        """Record and refuse."""
        self.server.seen.append(self.requestline)
        self.send_response(502)
        self.send_header("Content-Length", "0")
        self.end_headers()

    do_GET = do_POST  # pylint: disable=invalid-name

    def log_message(self, *_a):  # pylint: disable=arguments-differ
        """Silent."""


@pytest.fixture(name="proxy")
def _proxy(monkeypatch):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Proxy)
    srv.seen = []
    threading.Thread(target=lambda: srv.serve_forever(poll_interval=0.05), daemon=True).start()
    for var in ("http_proxy", "HTTP_PROXY"):
        monkeypatch.setenv(var, f"http://127.0.0.1:{srv.server_address[1]}")
    for var in ("no_proxy", "NO_PROXY"):
        monkeypatch.delenv(var, raising=False)
    yield srv.seen
    srv.shutdown()
    srv.server_close()


def _registry(tmp_path, url, allow_remote=False, **extra):
    home = tmp_path / "h"
    spec = {"type": "openai_compat", "base_url": url, "model": "m", "embed_model": "e", **extra}
    cfg = Config(home=home, db_path=home / "db", blobs_dir=home / "b", vault_dir=home / "v",
                 backends={"o": spec}, tasks={"distill": ["o"]}, allow_remote=allow_remote)
    return Registry.from_config(cfg)


def test_local_openai_compat_ignores_env_proxy(tmp_path, proxy):
    """HTTP_PROXY must not receive the prompt of a local backend."""
    with OpenAIStub() as stub:
        reg = _registry(tmp_path, stub.base_url)
        reg.get("o").generate(MSG)
        reg.get("o").embed(["x"])
        assert len(stub.requests) == 2
    assert not proxy


def test_remote_openai_compat_keeps_env_proxy(tmp_path, proxy):
    """Ruling: a corporate proxy is legitimate for a remote backend (egress is logged)."""
    with OpenAIStub() as stub:
        reg = _registry(tmp_path, stub.base_url, allow_remote=True, locality="remote")
        with pytest.raises(Exception):  # the fake proxy answers 502
            reg.get("o").generate(MSG)
        assert not stub.requests
    assert proxy


def test_anthropic_on_loopback_ignores_env_proxy(monkeypatch, proxy):
    """An http loopback base_url is local traffic whatever the backend locality says."""
    monkeypatch.setenv("IP_ANTH_KEY", "dummy-key-not-real")
    with AnthropicStub() as stub:
        AnthropicBackend("a", "m", "IP_ANTH_KEY", base_url=stub.base_url).generate(MSG)
        assert stub.requests
    assert not proxy


def test_doctor_probe_ignores_env_proxy(tmp_path, monkeypatch, proxy):
    """doctor probes carry the API key: they must not be proxied either."""
    monkeypatch.setenv("DUMMY_KEY_ENV", "dummy-key-not-real")
    with OpenAIStub() as stub:
        home = tmp_path / "h"
        be = {"type": "openai_compat", "base_url": stub.base_url, "model": "m", "embed_model": "e",
              "api_key_env": "DUMMY_KEY_ENV"}
        cfg = Config(home=home, db_path=home / "db", blobs_dir=home / "b", vault_dir=home / "v",
                     backends={"l": be}, tasks={}, allow_remote=False)
        check = next(c for c in doctor.run(cfg) if c.name == "backend:l")
        assert check.level == "OK" and stub.requests
    assert not proxy
