"""Adapter tests: fs drop folder, Telegram export import, HTTP ingest, and related fixes."""
import ast
import functools
import http.client
import inspect
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from pith.adapters.fs import FsAdapter
from pith import netguard
from pith.adapters import http_ingest
from pith.adapters.http_ingest import IngestServer, handle, load_token
from pith.adapters.telegram_export import flatten_text, import_export
from pith.store import db

FIX = Path(__file__).parent / "fixtures" / "telegram_export"
PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 20


def old(path, secs=10):
    """Old."""
    t = time.time() - secs
    os.utime(path, (t, t))


def mk(d, name, data=b"hello world note"):
    """Mk."""
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    if isinstance(data, bytes):
        p.write_bytes(data)
    else:
        p.write_text(data)
    old(p)
    return p


def rows(svc):
    """Rows."""
    return svc.conn.execute("SELECT * FROM inbox_items").fetchall()


# ---------- fs ----------
def test_fs_skips_icloud_stub_and_dotfiles(svc, tmp_path):
    """Test fs skips icloud stub and dotfiles."""
    d = tmp_path / "drop"
    for n in (".hidden.txt", "doc.pdf.icloud", "a.part", "b.tmp", "c.crdownload"):
        mk(d, n)
    keep = mk(d, "ok.md", "# real note")
    fa = FsAdapter(svc.inbox, [d], stable_polls=1)
    assert fa.poll() == 1
    assert len(rows(svc)) == 1 and not keep.exists() and (d / ".processed" / "ok.md").exists()
    assert (d / ".hidden.txt").exists() and (d / "doc.pdf.icloud").exists()


def test_fs_waits_for_stable_size_and_age(svc, tmp_path):
    """Test fs waits for stable size and age."""
    d = tmp_path / "drop"
    p = mk(d, "g.txt", "one")
    fa = FsAdapter(svc.inbox, [d], stable_polls=2)
    assert fa.poll() == 0           # first sighting
    p.write_text("one two")         # grew
    old(p)
    assert fa.poll() == 0           # size changed -> restart
    assert fa.poll() == 1           # stable twice
    fresh = d / "fresh.txt"
    fresh.write_text("new")          # mtime now: <2s old
    fa2 = FsAdapter(svc.inbox, [d], stable_polls=1)
    assert fa2.poll() == 0 and fresh.exists()


def test_fs_source_kept_if_submit_fails_and_rerun_is_idempotent(svc, tmp_path):
    """Test fs source kept if submit fails and rerun is idempotent."""
    d = tmp_path / "drop"
    p = mk(d, "n.txt", "important thought")
    fa = FsAdapter(svc.inbox, [d], stable_polls=1)
    real = svc.inbox.submit
    svc.inbox.submit = lambda **k: (_ for _ in ()).throw(RuntimeError("db locked"))
    assert fa.poll() == 0 and p.exists() and not (d / ".processed").exists()
    # crash AFTER submit, before move
    svc.inbox.submit = real
    real_move = shutil.move
    shutil.move = lambda *a, **k: (_ for _ in ()).throw(OSError("boom"))
    try:
        fa.poll()
    finally:
        shutil.move = real_move
    assert p.exists() and len(rows(svc)) == 1
    assert fa.poll() == 1           # re-run: dedupes by content, moves
    assert len(rows(svc)) == 1 and not p.exists()


def test_fs_url_file_becomes_url_submission(svc, tmp_path):
    """Test fs url file becomes url submission."""
    d = tmp_path / "drop"
    mk(d, "a.url", "[InternetShortcut]\nURL=https://example.com/x?utm_source=q\n")
    mk(d, "b.webloc", '<?xml version="1.0"?><plist version="1.0"><dict><key>URL</key>'
                      '<string>https://example.org/w</string></dict></plist>')
    mk(d, "links.txt", "https://example.com/1\n\nhttps://example.com/2\n")
    mk(d, "one.txt", "https://example.com/3")
    mk(d, "prose.txt", "see https://example.com/4 for more")
    FsAdapter(svc.inbox, [d], stable_polls=1).poll()
    urls = sorted(r["canonical_url"] for r in rows(svc) if r["canonical_url"])
    assert urls == ["https://example.com/1", "https://example.com/2", "https://example.com/3",
                    "https://example.com/x", "https://example.org/w"]
    assert any(r["kind_hint"] == "file" and r["original_filename"] == "prose.txt"
               for r in rows(svc))


def test_fs_symlink_escape_and_size_cap(svc, tmp_path):
    """Test fs symlink escape and size cap."""
    d = tmp_path / "drop"
    d.mkdir()
    secret = mk(tmp_path, "secret.txt", "top secret")
    (d / "link.txt").symlink_to(secret)
    big = mk(d, "big.bin", b"x" * 50)
    svc.cfg.max_fetch_bytes = 10
    fa = FsAdapter(svc.inbox, [d], stable_polls=1)
    assert fa.poll() == 0 and rows(svc) == [] and big.exists() and secret.exists()


# ---------- telegram ----------
def test_telegram_flatten_mixed_text_entities():
    """Test telegram flatten mixed text entities."""
    assert flatten_text("x") == "x"
    assert flatten_text(["a ", {"type": "bold", "text": "b"}, " c"]) == "a b c"
    assert flatten_text(None) == ""


def test_telegram_import_dedupes_on_rerun(svc):
    """Test telegram import dedupes on rerun."""
    r1 = import_export(svc.inbox, FIX / "result.json")
    n = len(rows(svc))
    r2 = import_export(svc.inbox, FIX / "result.json")
    assert len(rows(svc)) == n and r2.submitted == 0 and r2.duplicates == r1.submitted
    assert r1.skipped >= 1  # service message
    assert all(r["adapter"] == "telegram_export" for r in rows(svc))
    by = {r["external_id"]: r for r in rows(svc)}
    assert by["777:2"]["payload_text"] == "plain note about sourdough"
    assert "2024-01-02" in by["777:2"]["user_context"]
    assert "Some Channel" in by["777:5"]["user_context"]
    assert by["777:4"]["canonical_url"] is None       # URL-only message: note by default
    assert by["777:4"]["payload_text"] == "https://example.net/only"
    assert by["777:4"]["kind_hint"] == "text"
    assert "https://example.org/b" in by["777:3"]["payload_text"]  # text_link href extracted
    assert by["777:3"]["kind_hint"] == "text"
    assert "777:1" not in by


def test_telegram_since_filter(svc):
    """Test telegram since filter."""
    import_export(svc.inbox, FIX / "result.json", since="2024-01-05")
    ids = {x["external_id"] for x in rows(svc)}
    assert ids >= {"777:5", "777:6"} and "777:2" not in ids


def test_telegram_photo_and_file_attached(svc):
    """Test telegram photo and file attached."""
    import_export(svc.inbox, FIX / "result.json")
    by = {r["external_id"]: r for r in rows(svc)}
    p = by["777:6"]
    assert p["kind_hint"] == "file" and p["original_filename"] == "p1.jpg"
    assert "a photo caption" in p["user_context"]
    assert svc.blobs.exists(p["blob_sha256"])
    miss = by["777:7"]  # missing media: note, no crash
    assert miss["kind_hint"] == "text"
    assert "missing media" in miss["payload_text"] + (miss["user_context"] or "")
    assert "777:8" not in by or by["777:8"]["kind_hint"] == "text"  # path traversal never read
    assert not any(r["blob_sha256"] and b"root:" in svc.blobs.path(r["blob_sha256"]).read_bytes()
                   for r in rows(svc))


# ---------- equivalence & layering ----------
def test_adapters_produce_equivalent_rows(svc, tmp_path):
    """Test adapters produce equivalent rows."""
    d = tmp_path / "drop"
    mk(d, "n.md", "fs note")
    FsAdapter(svc.inbox, [d], stable_polls=1).poll()
    import_export(svc.inbox, FIX / "result.json")
    handle(svc.inbox, {"text": "http note"})
    rs = rows(svc)
    assert {r["adapter"] for r in rs} == {"fs", "telegram_export", "http"}
    assert {r["status"] for r in rs} == {"pending"}
    assert svc.conn.execute("SELECT count(*) FROM jobs").fetchone()[0] == len(rs)
    assert all(r["id"] and r["submitted_at"] and r["kind_hint"] in ("text", "file", "url")
               for r in rs)


def test_core_does_not_import_adapters():
    """Test core does not import adapters."""
    src = Path(__file__).parent.parent / "src" / "pith"
    bad = []
    for p in src.rglob("*.py"):
        if "adapters" in p.parts or p.name in ("cli.py", "run_all.py"):  # edge layers
            continue
        for n in ast.walk(ast.parse(p.read_text())):
            if isinstance(n, ast.Import):
                mods = [a.name for a in n.names]
            elif isinstance(n, ast.ImportFrom):
                mods = [n.module or ""]
            else:
                mods = []
            if any(m.startswith("pith.adapters") for m in mods):
                bad.append(str(p))
    assert not bad


# ---------- http ----------
def test_http_ingest_validates_body(svc):
    """Test http ingest validates body."""
    ok = handle(svc.inbox, {"url": "https://example.com/p", "context": "c"})
    assert set(ok) == {"id", "status", "duplicate"}
    assert ok["status"] == "pending" and ok["duplicate"] is False
    assert handle(svc.inbox, {"url": "https://example.com/p"})["duplicate"] is True
    for bad in ({}, {"text": "a", "url": "https://x.org"}, {"url": "ftp://x"}, {"text": ""},
                {"text": 5}, {"text": "a", "context": 3}, "str", {"url": "javascript:1"}):
        with pytest.raises(ValueError):
            handle(svc.inbox, bad)


@pytest.fixture(name="server")
def server_fixture(svc):
    """Running ingest server on an ephemeral port."""
    s = IngestServer(svc.cfg, port=0)
    t = threading.Thread(target=s.serve_forever, daemon=True)
    t.start()
    yield s
    s.shutdown()
    s.server_close()
    t.join(5)
    assert not t.is_alive()


def req(s, method, path, body=None, headers=None, **kw):
    """Send one request; token= overrides the auth (True = the real token, None = none)."""
    token = kw.get("token", True)
    c = http.client.HTTPConnection("127.0.0.1", s.server_address[1], timeout=10)
    h = {"Authorization": f"Bearer {s.token}"} if token is True else (
        {"X-Token": token} if token else {})
    c.request(method, path, body=body, headers={**h, **(headers or {})})
    r = c.getresponse()
    data = r.read()
    c.close()
    try:
        return r.status, json.loads(data), dict(r.getheaders())
    except ValueError:
        return r.status, data, dict(r.getheaders())


def test_http_server_auth_routes_and_errors(server, svc):
    """Test http server auth routes and errors."""
    assert server.server_address[0] == "127.0.0.1"
    tok = Path(svc.cfg.home / "http_token")
    assert tok.read_text(encoding="utf-8").strip() == server.token
    assert (tok.stat().st_mode & 0o777) == 0o600
    assert load_token(svc.cfg) == server.token
    hdr = {"Content-Type": "application/json"}
    assert req(server, "POST", "/v1/inbox", b"{}", hdr, token=None)[0] == 401
    assert req(server, "POST", "/v1/inbox", b"{}", hdr, token="wrong")[0] == 401
    s, b, h = req(server, "POST", "/v1/inbox", json.dumps({"text": "hello via http"}).encode(), hdr)
    assert s == 200 and b["status"] == "pending" and "Access-Control-Allow-Origin" not in h
    s2 = req(server, "POST", "/v1/inbox", json.dumps({"text": "x2"}).encode(), hdr,
             token=server.token)[0]  # X-Token path
    assert s2 == 200
    g = req(server, "GET", f"/v1/inbox/{b['id']}", token=server.token)
    assert g[0] == 200 and g[1]["id"] == b["id"]
    assert req(server, "GET", "/v1/inbox/nope")[0] == 404
    assert req(server, "GET", "/v1/nothing")[0] == 404
    for bad in (b"{not json", b"[1]", b'{"text": 5}', b""):
        s, b, _ = req(server, "POST", "/v1/inbox", bad, hdr)
        assert s == 400 and "Traceback" not in json.dumps(b)
    big = b"x" * (svc.cfg.max_fetch_bytes + 1)
    c = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=10)
    c.putrequest("POST", "/v1/inbox")
    c.putheader("Authorization", f"Bearer {server.token}")
    c.putheader("Content-Length", str(len(big)))
    c.endheaders()
    assert c.getresponse().status == 413
    c.close()
    for m in ("PUT", "DELETE", "PATCH", "HEAD"):
        st, _, h = req(server, m, "/v1/inbox", b"" if m != "HEAD" else None)
        assert st == 405 and "POST" in h.get("Allow", ""), m
    assert req(server, "POST", "/v1/inbox", json.dumps({"file": "abc"}).encode(), hdr)[0] == 400


def test_http_file_upload_raw_and_multipart(server, svc):
    """Test http file upload raw and multipart."""
    s, b, _ = req(server, "POST", "/v1/inbox", PNG,
                  {"Content-Type": "image/png", "X-Filename": "../../evil name.png"})
    assert s == 200
    row = svc.inbox.get(b["id"])
    assert row["original_filename"] == "evil name.png" and svc.blobs.exists(row["blob_sha256"])
    bd = "BOUND"
    body = (f'--{bd}\r\nContent-Disposition: form-data; name="context"\r\n\r\nfrom form\r\n'
            f'--{bd}\r\nContent-Disposition: form-data; name="file"; filename="n.md"\r\n'
            f'Content-Type: text/markdown\r\n\r\n# multipart note\r\n--{bd}--\r\n').encode()
    s, b, _ = req(server, "POST", "/v1/inbox", body,
                  {"Content-Type": f"multipart/form-data; boundary={bd}"})
    assert s == 200
    row = svc.inbox.get(b["id"])
    assert row["original_filename"] == "n.md" and row["user_context"] == "from form"


def test_http_refuses_nonloopback_without_explicit_token(svc):
    """Test http refuses nonloopback without explicit token."""
    svc.cfg.http_bind = "0.0.0.0"
    with pytest.raises(ValueError):
        IngestServer(svc.cfg, port=0)
    svc.cfg.http_token = "explicit-token"
    s = IngestServer(svc.cfg, port=0)
    assert s.token == "explicit-token"
    s.server_close()


def _run_cli(env, *a):
    """Run the pith CLI in a subprocess."""
    return subprocess.run([sys.executable, "-m", "pith.cli", *a], env=env, check=False,
                          capture_output=True, text=True, timeout=60)


def test_cli_import_telegram_and_adapters_list(tmp_path):
    """Test cli import telegram and adapters list."""
    env = {**os.environ, "PITH_HOME": str(tmp_path / "h")}
    run = functools.partial(_run_cli, env)
    assert "telegram_export" in run("adapters", "list").stdout
    r1 = run("import-telegram", str(FIX / "result.json"))
    assert r1.returncode == 0 and "submitted 6" in r1.stdout, r1.stdout + r1.stderr
    assert "submitted 0, duplicates 6" in run("import-telegram", str(FIX / "result.json")).stdout


# ---------- fix round 1 ----------
def _bad(tmp_path, content):
    """Bad."""
    p = tmp_path / "result.json"
    if content is not None:
        p.write_text(content)
    return p


@pytest.mark.parametrize("content", ["", '{"messages": [{"id": 1,', "[1, 2]", '{"messages": 5}',
                                     '"str"', None])
def test_telegram_bad_export_raises_valueerror(svc, tmp_path, content):
    """Test telegram bad export raises valueerror."""
    with pytest.raises(ValueError, match="not a Telegram export"):
        import_export(svc.inbox, _bad(tmp_path, content))


def test_telegram_non_dict_messages_skipped(svc, tmp_path):
    """Test telegram non dict messages skipped."""
    p = _bad(tmp_path, json.dumps({"id": 1, "messages": [
        1, "x", None, {"id": 2, "type": "message", "text": "ok"}]}))
    r = import_export(svc.inbox, p)
    assert r.submitted == 1 and r.skipped == 3


def test_cli_import_telegram_bad_file_clean_error(tmp_path):
    """Test cli import telegram bad file clean error."""
    env = {**os.environ, "PITH_HOME": str(tmp_path / "h")}
    for target in (tmp_path / "missing.json", _bad(tmp_path, "{")):
        r = _run_cli(env, "import-telegram", str(target))
        assert r.returncode != 0 and "Traceback" not in r.stderr and r.stderr.startswith("error:")


def _counts(svc):
    """Counts."""
    return (svc.conn.execute("SELECT count(*) FROM provenance_log").fetchone()[0],
            svc.conn.execute(
                "SELECT coalesce(sum(length(user_context)),0) FROM inbox_items").fetchone()[0],
            svc.conn.execute("SELECT count(*) FROM inbox_items").fetchone()[0],
            svc.conn.execute("SELECT count(*) FROM jobs").fetchone()[0])


def test_telegram_reimport_is_pure_noop_for_deduped_messages(svc, tmp_path):
    """Test telegram reimport is pure noop for deduped messages."""
    exp = tmp_path / "exp"
    (exp / "photos").mkdir(parents=True)
    (exp / "photos" / "a.jpg").write_bytes(PNG)
    (exp / "photos" / "b.jpg").write_bytes(PNG)  # same blob twice
    msgs = [
        {"id": 1, "type": "message", "date": "d1", "text": "same words again"},
        {"id": 2, "type": "message", "date": "d2",
         "text": [{"type": "link", "text": "https://example.com/dup"}]},
        {"id": 3, "type": "message", "date": "d3",
         "text": [{"type": "link", "text": "https://example.com/dup?utm_source=z"}]},
        {"id": 4, "type": "message", "date": "d4", "forwarded_from": "X", "text": "cap",
         "photo": "photos/a.jpg"},
        {"id": 5, "type": "message", "date": "d5", "forwarded_from": "X", "text": "cap",
         "photo": "photos/b.jpg"},
    ]
    p = exp / "result.json"
    p.write_text(json.dumps({"id": 9, "messages": msgs}))
    import_export(svc.inbox, p, fetch_urls=True)
    # make the deduped URL item dead: a re-run must not revive it
    svc.conn.execute("UPDATE inbox_items SET status='failed' WHERE canonical_url IS NOT NULL")
    before = _counts(svc)
    r2 = import_export(svc.inbox, p, fetch_urls=True)
    assert _counts(svc) == before and r2.submitted == 0
    failed = svc.conn.execute("SELECT count(*) FROM inbox_items WHERE status='failed'")
    assert failed.fetchone()[0] == 1


def test_fs_rerun_after_crash_is_pure_noop(svc, tmp_path):
    """Test fs rerun after crash is pure noop."""
    d = tmp_path / "drop"
    mk(d, "links.txt", "https://example.com/q1\nhttps://example.com/q2\n")
    mk(d, "n.md", "# note")
    fa = FsAdapter(svc.inbox, [d], stable_polls=1)
    real_move = shutil.move
    shutil.move = lambda *a, **k: (_ for _ in ()).throw(OSError("boom"))
    try:
        fa.poll()
    finally:
        shutil.move = real_move
    before = _counts(svc)
    assert fa.poll() == 2
    assert _counts(svc) == before


def test_fs_processed_name_collision_never_overwrites(svc, tmp_path):
    """Test fs processed name collision never overwrites."""
    d = tmp_path / "drop"
    fa = FsAdapter(svc.inbox, [d], stable_polls=1)
    mk(d, "same.md", "first content")
    fa.poll()
    mk(d, "same.md", "second content")
    fa.poll()
    mk(d, "same.md", "third content")
    fa.poll()
    kept = sorted(f.read_text() for f in (d / ".processed").iterdir())
    assert kept == ["first content", "second content", "third content"]


def test_telegram_only_missing_media_is_skipped(svc, tmp_path):
    """Test telegram only missing media is skipped."""
    p = _bad(tmp_path, json.dumps({"id": 1, "messages": [
        {"id": 1, "type": "message", "date": "d", "text": "", "photo": "photos/none.jpg"}]}))
    r = import_export(svc.inbox, p)
    assert (r.submitted, r.skipped) == (0, 1) and rows(svc) == []


def test_http_token_empty_or_loose_mode(svc):
    """Test http token empty or loose mode."""
    tf = svc.cfg.home / "http_token"
    tf.parent.mkdir(parents=True, exist_ok=True)
    tf.write_text("\n")
    t = load_token(svc.cfg)
    assert t and tf.read_text().strip() == t
    tf.chmod(0o644)
    assert load_token(svc.cfg) == t and (tf.stat().st_mode & 0o777) == 0o600


@pytest.mark.usefixtures("server")
def test_http_slow_client_times_out():
    """Test http slow client times out."""
    handler = http_ingest._Handler  # pylint: disable=protected-access  # white-box timeout check
    assert handler.timeout and handler.timeout <= 60


def test_migrate_v1_db_with_rows_keeps_data(tmp_path):
    """Test migrate v1 db with rows keeps data."""
    conn = db.connect(tmp_path / "v1.db")
    sql = (Path(db.__file__).parent / "migrations" / "001_init.sql").read_text()
    for st in db._split(sql):  # pylint: disable=protected-access  # replay v1 migration
        conn.execute(st)
    conn.execute("PRAGMA user_version=1")
    conn.execute("INSERT INTO inbox_items(id,adapter,submitted_at,status,payload_text,"
                 "canonical_url,updated_at)"
                 " VALUES ('a','cli','t','pending','hi','http://x','t')")
    assert db.migrate(conn) == 8
    r = conn.execute("SELECT * FROM inbox_items WHERE id='a'").fetchone()
    assert r["payload_text"] == "hi" and r["external_id"] is None
    conn.execute("INSERT INTO external_ids(adapter, external_id, inbox_id) VALUES ('x','1','a')")


def test_http_405_drains_body_and_closes_connection(server):
    """Test http 405 drains body and closes connection."""
    s = socket.create_connection(("127.0.0.1", server.server_address[1]), timeout=5)
    body = b"x" * 5000
    s.sendall(f"PUT /v1/inbox HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer {server.token}\r\n"
              f"Content-Length: {len(body)}\r\n\r\n".encode() + body)
    resp = b""
    while chunk := s.recv(4096):
        resp += chunk  # server must close the socket (Connection: close) or this would hang
    assert resp.startswith(b"HTTP/1.1 405") and b"connection: close" in resp.lower()
    s.close()


def test_load_token_is_exclusive_and_never_rewrites(svc):
    """Test load token is exclusive and never rewrites."""
    tf = svc.cfg.home / "http_token"
    tf.parent.mkdir(parents=True, exist_ok=True)
    tf.write_text("existing-token\n")
    assert load_token(svc.cfg) == "existing-token" and tf.read_text() == "existing-token\n"
    tf.unlink()
    out = []
    ts = [threading.Thread(target=lambda: out.append(load_token(svc.cfg))) for _ in range(8)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len(set(out)) == 1 and tf.read_text().strip() == out[0]


def test_context_dedupe_with_blank_lines_inside_context(svc):
    """Test context dedupe with blank lines inside context."""
    url = "https://example.com/ctx"
    a = svc.inbox.submit(adapter="t", text=url, user_context="line one\n\nline two")
    svc.inbox.submit(adapter="t", text=url, user_context="line one\n\nline two")
    svc.inbox.submit(adapter="t", text=url, user_context="line two")
    assert svc.inbox.get(a.id)["user_context"] == "line one\n\nline two"


def test_telegram_fetch_urls_is_opt_in_and_stays_untrusted(svc):
    """The library default keeps URLs as notes; fetch_urls=True fetches them as untrusted rows."""
    assert inspect.signature(import_export).parameters["fetch_urls"].default is False
    import_export(svc.inbox, FIX / "result.json", fetch_urls=True)
    only = {r["external_id"]: r for r in rows(svc)}["777:4"]
    assert only["canonical_url"] == "https://example.net/only" and only["kind_hint"] == "url"
    assert netguard.untrusted(only)
