"""Backend locality is inferred from base_url unless declared; remote means blocked by default."""

import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from pith import cli, doctor
from pith.config import Config
from pith.providers import egress, locality
from pith.providers.openai_compat import OpenAICompatBackend
from pith.providers.ports import ProviderError, RemoteBlocked
from pith.providers.registry import Registry

LAN = "http://192.0.2.7:9/v1"  # TEST-NET-1: never routable


def _cfg(tmp_path, backends, allow_remote=False):
    return Config(home=tmp_path, db_path=tmp_path / "db", blobs_dir=tmp_path / "b",
                  vault_dir=tmp_path / "v", backends=backends,
                  tasks={"distill": list(backends)}, allow_remote=allow_remote)


@pytest.mark.parametrize("url", ["http://localhost:11434/v1", "http://127.0.0.1:1/v1",
                                 "http://127.8.9.1/v1", "http://[::1]:8080/v1"])
def test_loopback_hosts_are_local(url):
    """localhost, 127.0.0.0/8 and ::1 are local without any declaration."""
    assert locality.resolve({}, url) == "local"


@pytest.mark.parametrize("url", ["https://api.openai.com/v1", LAN, "http://0.0.0.0:1/v1",
                                 "http://my-box.lan/v1", "http://127.0.0.1.evil.example/v1"])
def test_other_hosts_are_remote_when_undeclared(url):
    """Anything that is not loopback counts as remote unless declared otherwise."""
    assert locality.resolve({}, url) == "remote"


def test_locality_value_is_validated(tmp_path):
    """A typo such as 'Remote' is a config error, not silently local."""
    spec = {"type": "openai_compat", "base_url": LAN, "model": "m", "locality": "Remote"}
    with pytest.raises(ValueError, match="locality must be"):
        Registry.from_config(_cfg(tmp_path, {"x": spec}))
    spec = {"type": "cli", "command": ["x"], "locality": "elsewhere"}
    with pytest.raises(ValueError, match="locality must be"):
        Registry.from_config(_cfg(tmp_path, {"x": spec}))


@pytest.fixture(name="events")
def _events():
    """Install an egress sink that records every announced call."""
    seen = []
    token = egress.sink.set(lambda *a: seen.append(a))
    yield seen
    egress.sink.reset(token)


def test_undeclared_non_loopback_backend_is_refused_and_sends_nothing(
        tmp_path, monkeypatch, events):
    """With allow_remote=false the registry refuses it: no socket, no egress event."""

    def no_network(*a, **k):
        raise AssertionError(f"network used: {a}")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    spec = {"type": "openai_compat", "base_url": "https://api.openai.com/v1", "model": "m"}
    reg = Registry.from_config(_cfg(tmp_path, {"hosted": spec}))
    assert [b.name for b in reg.chain("distill")] == ["heuristic"]
    assert reg.skipped and reg.skipped[0]["name"] == "hosted"
    with pytest.raises(RemoteBlocked):
        reg.get("hosted")
    assert not events


def test_undeclared_non_loopback_backend_reports_egress_when_allowed(
        tmp_path, monkeypatch, events):
    """Allowed remote traffic is announced to the egress sink before the call."""
    monkeypatch.setattr("urllib.request.OpenerDirector.open",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("offline")))
    spec = {"type": "openai_compat", "base_url": LAN, "model": "m"}
    reg = Registry.from_config(_cfg(tmp_path, {"lan": spec}, allow_remote=True))
    with pytest.raises(ProviderError):
        reg.get("lan").generate([{"role": "user", "content": "secret"}])
    assert events and events[0][0] == "lan"


def test_declared_local_on_lan_host_is_honoured_but_warned(tmp_path):
    """An explicit local on a non-loopback host stays possible; doctor warns about it."""
    spec = {"type": "openai_compat", "base_url": LAN, "model": "m", "locality": "local"}
    cfg = _cfg(tmp_path, {"lan": spec})
    assert [b.name for b in Registry.from_config(cfg).chain("distill")] == ["lan", "heuristic"]
    assert len(locality.warnings(cfg.backends)) == 1 and "lan" in locality.warnings(cfg.backends)[0]
    ok = {"type": "openai_compat", "base_url": "http://localhost:1/v1", "model": "m",
          "locality": "local"}
    assert not locality.warnings({"ok": ok})


def test_cli_doctor_prints_the_locality_warning(tmp_path, monkeypatch, capsys):
    """`pith doctor` surfaces the warning and the egress command states the cli trust rule."""
    conf = tmp_path / "c.toml"
    conf.write_text(f'[backends.lan]\ntype = "openai_compat"\nbase_url = "{LAN}"\nmodel = "m"\n'
                    'locality = "local"\n')
    monkeypatch.setattr(doctor, "run", lambda cfg, full=False: [])
    with pytest.raises(SystemExit) as ex:
        cli.main(["--home", str(tmp_path / "h"), "--config", str(conf), "doctor"])
    assert ex.value.code == 0
    assert "[WARN ] locality" in capsys.readouterr().out
    cli.main(["--home", str(tmp_path / "h"), "--config", str(conf), "egress"])
    assert "cli backends are trusted as declared" in capsys.readouterr().out


class _Redirector(BaseHTTPRequestHandler):
    """Answers every POST with a 302 to the recorder on the other port."""

    def log_message(self, *a):
        """Silence the request log."""

    def do_POST(self):  # pylint: disable=invalid-name  # http.server naming
        """Redirect to the other stub."""
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self.send_response(302)
        self.send_header("Location", self.server.target + self.path)
        self.send_header("Content-Length", "0")
        self.end_headers()


class _Recorder(BaseHTTPRequestHandler):
    """Records the headers of any request that reaches it."""

    def log_message(self, *a):
        """Silence the request log."""

    def do_GET(self):  # pylint: disable=invalid-name  # http.server naming
        """Record and answer an empty object."""
        self.server.seen.append(dict(self.headers))
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"{}")


def _serve(handler):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_openai_compat_does_not_follow_redirects_with_the_key(monkeypatch):
    """A 30x from base_url must not re-send Authorization to the redirect target."""
    monkeypatch.setenv("TEST_KEY", "sk-secret")
    recorder, redirector = _serve(_Recorder), _serve(_Redirector)
    recorder.seen = []
    redirector.target = f"http://127.0.0.1:{recorder.server_port}"
    try:
        b = OpenAICompatBackend("r", f"http://127.0.0.1:{redirector.server_port}/v1", "m",
                                api_key_env="TEST_KEY")
        with pytest.raises(ProviderError, match="302"):
            b.generate([{"role": "user", "content": "hi"}])
    finally:
        for srv in (recorder, redirector):
            srv.shutdown()
            srv.server_close()
    assert not recorder.seen
