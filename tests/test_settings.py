"""Settings tab backend: config discovery, safe save, live apply, bare-command launch."""
import threading
import tomllib

import pytest
from test_dashboard import Client

from infoparser import cli, settings
from infoparser.adapters.http_ingest import load_token
from infoparser.config import load_config
from infoparser.dashboard.server import make_server
from infoparser.services import build

LOCAL = {"type": "openai_compat", "base_url": "http://localhost:11434/v1", "model": "m1",
         "locality": "local"}
BODY = {"backends": {"local": LOCAL}, "tasks": {"distill": ["local"]}, "allow_remote": False}


@pytest.fixture(name="home")
def home_fixture(tmp_path, monkeypatch):
    """A fresh home reached only through INFOPARSER_HOME (no explicit config file)."""
    monkeypatch.delenv("INFOPARSER_CONFIG", raising=False)
    monkeypatch.setenv("INFOPARSER_HOME", str(tmp_path / "home"))
    return tmp_path / "home"


def test_config_discovered_in_home_and_its_home_key_ignored(home):
    """<home>/config.toml is picked up without flags; a `home` key inside it cannot move the home."""
    home.mkdir()
    (home / "config.toml").write_text('home = "/elsewhere"\n[privacy]\nallow_remote = true\n')
    cfg = load_config()
    assert cfg.allow_remote is True and cfg.home == home and cfg.source == home / "config.toml"


def test_save_round_trips_through_the_file_and_keeps_other_keys(home):
    """Save writes backends/tasks/allow_remote, keeps unrelated keys, and keeps a .bak."""
    home.mkdir()
    (home / "config.toml").write_text('[limits]\nmax_attempts = 9\n# note\n')
    new = settings.save(load_config(), BODY)
    raw = tomllib.loads((home / "config.toml").read_text())
    assert raw["limits"] == {"max_attempts": 9} and raw["backends"]["local"] == LOCAL
    assert raw["tasks"] == {"distill": ["local"]} and raw["privacy"] == {"allow_remote": False}
    assert (home / "config.toml.bak").read_text().endswith("# note\n")
    assert load_config().backends == new.backends and new.max_attempts == 9


def test_save_creates_the_file_on_first_use(home):
    """With no config file yet, the first save creates <home>/config.toml (0600)."""
    settings.save(load_config(), BODY)
    p = home / "config.toml"
    assert p.is_file() and p.stat().st_mode & 0o777 == 0o600
    assert load_config().source == p


def test_cli_backend_cannot_be_added_or_changed_from_the_ui(home):
    """Exec-capable types are file-only; an existing one passes through unchanged."""
    home.mkdir()
    shell = {"type": "cli", "command": ["echo", "x"]}
    (home / "config.toml").write_text('[backends.sh]\ntype = "cli"\ncommand = ["echo", "x"]\n')
    cfg = load_config()
    with pytest.raises(ValueError, match="config file"):
        settings.save(cfg, {**BODY, "backends": {"evil": {"type": "cli", "command": ["sh"]}}})
    with pytest.raises(ValueError, match="config file"):
        settings.save(cfg, {**BODY, "backends": {"sh": {**shell, "command": ["sh"]}}})
    settings.save(cfg, {**BODY, "backends": {"sh": shell, "local": LOCAL}})  # unchanged: fine
    assert load_config().backends["sh"] == shell


def test_unknown_keys_and_bad_names_rejected(home):
    """UI types accept only their allowlisted keys; names cannot hold ':' or dots."""
    cfg = load_config()
    with pytest.raises(ValueError, match="not editable"):
        settings.save(cfg, {**BODY, "backends": {"l": {**LOCAL, "command": ["sh"]}}})
    with pytest.raises(ValueError, match="backend name"):
        settings.save(cfg, {**BODY, "backends": {"a:b": LOCAL}})


def test_invalid_config_is_rejected_and_file_untouched(home):
    """A bad task reference or number fails validation before anything is replaced."""
    home.mkdir()
    p = home / "config.toml"
    p.write_text('[backends.heuristic]\ntype = "heuristic"\n')
    before = p.read_text()
    with pytest.raises(ValueError, match="unknown backend"):
        settings.save(load_config(), {**BODY, "tasks": {"distill": ["ghost"]}})
    with pytest.raises(ValueError, match="positive number"):
        settings.save(load_config(), {**BODY, "backends": {"l": {**LOCAL, "context_window": "x"}}})
    assert p.read_text() == before and not list(home.glob(".config.toml.tmp*"))


def test_dumps_round_trips_awkward_strings():
    """The TOML writer survives quotes, unicode and odd keys."""
    data = {"a": {"b c": 'q"uote\\ é \U0001f600', "n": [1, 2], "f": 1.5, "t": True}}
    assert tomllib.loads(settings.dumps(data)) == data


def test_list_models_is_loopback_only():
    """Model detection refuses non-local hosts (no general URL fetcher)."""
    for url in ("http://example.com/v1", "file:///etc/passwd", None, "http://10.0.0.1/v1"):
        with pytest.raises(ValueError, match="this machine"):
            settings.list_models(url)


def test_api_save_applies_live_and_keeps_the_csrf_rule(home):
    """POST /api/config writes, swaps the live registry, rejects cookie POSTs without Origin."""
    svc = build(load_config())
    srv = make_server(svc, port=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    seen = []
    srv.listeners.append(seen.append)
    try:
        tok = load_token(svc.cfg)
        c = Client(srv, tok)
        st, view, _ = c.req("GET", "/api/config")
        assert st == 200 and view["backends"] == {} and "local" in view["presets"]
        assert Client(srv, tok, cookie=True).req("POST", "/api/config", BODY)[0] == 403
        old = svc.registry
        st, out, _ = c.req("POST", "/api/config", BODY)
        assert st == 200 and out["backends"]["local"]["editable"] is True
        assert svc.registry is not old and "local" in svc.registry.backends and len(seen) == 1
        st, err, _ = c.req("POST", "/api/config",
                           {**BODY, "backends": {"x": {"type": "cli", "command": ["sh"]}}})
        assert st == 400 and "config file" in err["error"]
        assert c.req("GET", "/api/models?base_url=http://example.com/v1")[0] == 400
    finally:
        srv.shutdown()
        srv.server_close()


def test_bare_command_means_run(monkeypatch):
    """`infoparser --home X` launches `run`; --open is terminal-only unless forced."""
    called = {}
    handler = lambda a: called.update(cmd=a.cmd, open=a.open)  # noqa: E731
    monkeypatch.setitem(cli.COMMANDS, "run", (handler, cli.COMMANDS["run"][1]))
    cli.main(["--home", "/tmp/x"])
    assert called == {"cmd": "run", "open": None}
    assert cli.build_parser().parse_args(["run", "--no-open"]).open is False


def test_detect_reports_cli_state(monkeypatch):
    """detect(): installed/logged-in per CLI from fixed status commands; gemini never probed."""
    ran = []

    def fake_run(argv, **_kw):
        ran.append(argv)
        out = '{"loggedIn": true}' if argv[0] == "claude" else ""
        return type("P", (), {"stdout": out, "returncode": 1 if argv[0] == "codex" else 0})()

    monkeypatch.setattr(settings.shutil, "which", lambda n: f"/bin/{n}" if n != "codex" else None)
    monkeypatch.setattr(settings.subprocess, "run", fake_run)
    monkeypatch.setattr(settings, "list_models", lambda _u: (_ for _ in ()).throw(ValueError("x")))
    got = {p["id"]: p for p in settings.detect()}
    assert got["claude"]["logged_in"] is True
    assert got["codex"]["installed"] is False and got["codex"]["logged_in"] is None
    assert got["gemini"]["installed"] and got["gemini"]["logged_in"] is None
    assert got["ollama"]["installed"] is False
    assert ran == [["claude", "auth", "status"]]  # only fixed argv, only for installed CLIs


def test_detect_survives_broken_status(monkeypatch):
    """A status command that times out or prints garbage yields logged_in None, never an error."""
    monkeypatch.setattr(settings.shutil, "which", lambda n: f"/bin/{n}")
    monkeypatch.setattr(settings, "list_models", lambda _u: ["m1"])

    def boom(argv, **_kw):
        raise settings.subprocess.TimeoutExpired(argv, 5)

    monkeypatch.setattr(settings.subprocess, "run", boom)
    got = {p["id"]: p for p in settings.detect()}
    assert got["claude"]["logged_in"] is None and got["codex"]["logged_in"] is None
    assert got["ollama"]["models"] == ["m1"]


def test_subscription_backend_is_server_authored(home):
    """The UI names a CLI + model; any command the client sends is discarded and rebuilt."""
    evil = {"type": "cli", "subscription": "codex", "model": "m-1", "command": ["sh", "-c", "x"]}
    settings.save(load_config(), {**BODY, "tasks": {}, "backends": {"cx": evil, "cl": {"subscription": "claude"}}})
    b = load_config().backends
    assert b["cx"]["command"][:4] == ["codex", "exec", "-m", "m-1"] and "sh" not in b["cx"]["command"]
    assert b["cl"]["command"][:3] == ["claude", "-p", "--tools"] and b["cl"]["locality"] == "remote"
    assert b["cx"]["locality"] == "remote"  # allow_remote applies to it
    assert settings.view(load_config())["backends"]["cx"]["editable"] is True


@pytest.mark.parametrize("sub", [
    {"subscription": "codex"},                       # codex needs a model
    {"subscription": "codex", "model": "--yolo"},    # a model can never be read as a flag
    {"subscription": "claude", "model": "a b"},
    {"subscription": "gemini"},                      # not on the allowlist
    {"subscription": "sh"},
])
def test_bad_subscription_rejected(home, sub):
    """Unknown CLI, missing model or a flag-like model: refused, nothing written."""
    with pytest.raises(ValueError):
        settings.save(load_config(), {**BODY, "backends": {"x": sub}})
    assert not (home / "config.toml").exists()
