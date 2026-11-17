"""Imported Telegram URLs: kept as notes by default, fetched only on opt-in and only publicly."""
import ipaddress
import json
import os
import socket
import subprocess
import sys

from stubs.http_fixture_server import FixtureServer, Route

from pith import netguard
from pith.adapters.telegram_export import import_export
from pith.cli import build_parser
from pith.config import load_config
from pith.pipeline import runner
from pith.services import build
from pith.worker import Failed, Processed

PAGE = Route(b"<html><body><article><h1>Hello</h1>" + b"<p>Public page body text. </p>" * 30
             + b"</article></body></html>")


def _export(tmp_path, url):
    msg = {"id": 1, "type": "message", "date": "2024-01-02T10:00:00", "from": "Mallory",
           "text": [{"type": "link", "text": url}],
           "text_entities": [{"type": "link", "text": url}]}
    path = tmp_path / "result.json"
    path.write_text(json.dumps({"name": "Group", "type": "private_group", "id": 5,
                                "messages": [msg]}), "utf-8")
    return path


def _row(svc):
    return svc.conn.execute("SELECT * FROM inbox_items").fetchone()


def test_default_keeps_url_as_a_note_and_never_fetches(svc, tmp_path):
    """Opt-in off: no fetch call is made and the URL is preserved exactly as submitted."""
    with FixtureServer({"/a": PAGE}) as srv:
        url = srv.base + "/a?utm_source=x"
        import_export(svc.inbox, _export(tmp_path, url), fetch_urls=False)
        row = _row(svc)
        assert row["kind_hint"] == "text" and row["canonical_url"] is None
        assert row["payload_text"] == url
        assert isinstance(runner.process(svc, row["id"]), Processed)
        assert not srv.hits
        assert svc.inbox.get(row["id"])["content_type"] == "note"


def test_opt_in_fetches_under_public_only_rules(svc, tmp_path):
    """Opt-in on: a loopback URL from chat content is refused before any request is sent."""
    with FixtureServer({"/a": PAGE}) as srv:
        import_export(svc.inbox, _export(tmp_path, srv.base + "/a"), fetch_urls=True)
        row = _row(svc)
        assert row["kind_hint"] == "url" and row["adapter"] == "telegram_export"
        out = runner.process(svc, row["id"])
        assert isinstance(out, Failed) and "non-public" in out.error
        assert not srv.hits


def test_opt_in_fetches_a_public_url_and_cites_it_as_submitted(svc, tmp_path, monkeypatch):
    """With the address treated as public the page is fetched and cited as submitted."""
    real = netguard.is_public
    monkeypatch.setattr(netguard, "is_public",
                        lambda ip: ip == ipaddress.ip_address("127.0.0.1") or real(ip))
    with FixtureServer({"/a": PAGE}) as srv:
        url = srv.base + "/a"
        import_export(svc.inbox, _export(tmp_path, url), fetch_urls=True)
        row = _row(svc)
        assert isinstance(runner.process(svc, row["id"]), Processed)
        assert srv.hits == ["/a"]
        assert svc.conn.execute("SELECT url FROM sources").fetchone()["url"] == url
        assert svc.inbox.get(row["id"])["payload_text"] == url


def test_untrusted_media_url_is_not_handed_to_yt_dlp(tmp_path, monkeypatch):
    """A non-public host never reaches yt-dlp, which follows its own redirects."""
    log = tmp_path / "ytdlp.log"
    monkeypatch.setenv("FAKE_YTDLP_LOG", str(log))
    fake = os.path.join(os.path.dirname(__file__), "stubs", "fake_ytdlp.py")
    svc = build(load_config(env={"PITH_HOME": str(tmp_path / "h"),
                                 "PITH_YT_DLP": fake}))
    import_export(svc.inbox, _export(tmp_path, "http://127.0.0.1:9/clip.mp4"), fetch_urls=True)
    out = runner.process(svc, _row(svc)["id"])
    assert isinstance(out, Failed) and "non-public" in out.error and not log.exists()


def test_cli_flag_and_default(tmp_path):
    """`import-telegram` stores notes by default; --fetch-urls queues a URL item."""
    args = build_parser().parse_args(["import-telegram", "x"])
    assert args.fetch_urls is False
    env = {**os.environ, "PITH_HOME": str(tmp_path / "h")}
    src = _export(tmp_path, "https://example.net/only")

    def run(*extra):
        return subprocess.run([sys.executable, "-m", "pith.cli", "import-telegram",
                               str(src), *extra], env=env, capture_output=True, text=True,
                              timeout=60, check=False)

    assert run().returncode == 0
    svc = build(load_config(env={"PITH_HOME": str(tmp_path / "h")}))
    assert _row(svc)["kind_hint"] == "text"
    svc.conn.execute("DELETE FROM external_ids")
    svc.conn.execute("DELETE FROM jobs")
    svc.conn.execute("DELETE FROM inbox_items")
    svc.conn.commit()
    assert run("--fetch-urls").returncode == 0
    assert _row(svc)["kind_hint"] == "url"
    helped = subprocess.run([sys.executable, "-m", "pith.cli", "import-telegram", "-h"],
                            env=env, capture_output=True, text=True, timeout=60, check=False)
    assert "--fetch-urls" in helped.stdout


def test_untrusted_caption_fallback_cannot_rebind_to_loopback(tmp_path, monkeypatch):
    """The login-wall caption fetch is untrusted too: a host that turns private is not fetched."""
    monkeypatch.setenv("FAKE_YTDLP_MODE", "login")
    fake = os.path.join(os.path.dirname(__file__), "stubs", "fake_ytdlp.py")
    svc = build(load_config(env={"PITH_HOME": str(tmp_path / "h"),
                                 "PITH_YT_DLP": fake}))
    answers = iter([["93.184.216.34"]])  # public once, then loopback (DNS rebinding)
    monkeypatch.setattr(netguard, "resolve", lambda h: next(answers, ["127.0.0.1"]))
    real_gai = socket.getaddrinfo
    monkeypatch.setattr(socket, "getaddrinfo", lambda h, *a, **k: real_gai(
        "127.0.0.1" if h == "rebind.test" else h, *a, **k))
    routes = {"/private.mp4": Route(b'<meta property="og:description" content="SECRET">')}
    with FixtureServer(routes) as srv:
        port = srv.base.rsplit(":", 1)[1]
        import_export(svc.inbox, _export(tmp_path, f"http://rebind.test:{port}/private.mp4"),
                      fetch_urls=True)
        runner.process(svc, _row(svc)["id"])
        assert not srv.hits
