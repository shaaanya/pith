import ast
import http.client
import json
import os
import shutil
import threading
import time
from pathlib import Path

import pytest

from infoparser.adapters import telegram_export
from infoparser.adapters.fs import FsAdapter
from infoparser.adapters.http_ingest import IngestServer, handle, load_token
from infoparser.adapters.telegram_export import flatten_text, import_export

FIX = Path(__file__).parent / "fixtures" / "telegram_export"
PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 20


def old(path, secs=10):
    t = time.time() - secs
    os.utime(path, (t, t))


def mk(d, name, data=b"hello world note"):
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_bytes(data) if isinstance(data, bytes) else p.write_text(data)
    old(p)
    return p


def rows(svc):
    return svc.conn.execute("SELECT * FROM inbox_items").fetchall()


# ---------- fs ----------
def test_fs_skips_icloud_stub_and_dotfiles(svc, tmp_path):
    d = tmp_path / "drop"
    for n in (".hidden.txt", "doc.pdf.icloud", "a.part", "b.tmp", "c.crdownload"):
        mk(d, n)
    keep = mk(d, "ok.md", "# real note")
    fa = FsAdapter(svc.inbox, [d], stable_polls=1)
    assert fa.poll() == 1
    assert len(rows(svc)) == 1 and not keep.exists() and (d / ".processed" / "ok.md").exists()
    assert (d / ".hidden.txt").exists() and (d / "doc.pdf.icloud").exists()


def test_fs_waits_for_stable_size_and_age(svc, tmp_path):
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
    assert any(r["kind_hint"] == "file" and r["original_filename"] == "prose.txt" for r in rows(svc))


def test_fs_symlink_escape_and_size_cap(svc, tmp_path):
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
    assert flatten_text("x") == "x"
    assert flatten_text(["a ", {"type": "bold", "text": "b"}, " c"]) == "a b c"
    assert flatten_text(None) == ""


def test_telegram_import_dedupes_on_rerun(svc):
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
    assert by["777:4"]["canonical_url"] == "https://example.net/only"       # URL-only message
    assert "https://example.org/b" in by["777:3"]["payload_text"]            # text_link href extracted
    assert by["777:3"]["kind_hint"] == "text"
    assert "777:1" not in by


def test_telegram_since_filter(svc):
    r = import_export(svc.inbox, FIX / "result.json", since="2024-01-05")
    assert {x["external_id"] for x in rows(svc)} >= {"777:5", "777:6"} and "777:2" not in {x["external_id"] for x in rows(svc)}


def test_telegram_photo_and_file_attached(svc):
    import_export(svc.inbox, FIX / "result.json")
    by = {r["external_id"]: r for r in rows(svc)}
    p = by["777:6"]
    assert p["kind_hint"] == "file" and p["original_filename"] == "p1.jpg" and "a photo caption" in p["user_context"]
    assert svc.blobs.exists(p["blob_sha256"])
    miss = by["777:7"]  # missing media: note, no crash
    assert miss["kind_hint"] == "text" and "missing media" in miss["payload_text"] + (miss["user_context"] or "")
    assert "777:8" not in by or by["777:8"]["kind_hint"] == "text"  # path traversal never read
    assert not any(r["blob_sha256"] and b"root:" in svc.blobs.path(r["blob_sha256"]).read_bytes() for r in rows(svc))


# ---------- equivalence & layering ----------
def test_adapters_produce_equivalent_rows(svc, tmp_path):
    d = tmp_path / "drop"
    mk(d, "n.md", "fs note")
    FsAdapter(svc.inbox, [d], stable_polls=1).poll()
    import_export(svc.inbox, FIX / "result.json")
    handle(svc.inbox, {"text": "http note"})
    rs = rows(svc)
    assert {r["adapter"] for r in rs} == {"fs", "telegram_export", "http"}
    assert {r["status"] for r in rs} == {"pending"}
    assert svc.conn.execute("SELECT count(*) FROM jobs").fetchone()[0] == len(rs)
    assert all(r["id"] and r["submitted_at"] and r["kind_hint"] in ("text", "file", "url") for r in rs)


def test_core_does_not_import_adapters():
    src = Path(__file__).parent.parent / "src" / "infoparser"
    bad = []
    for p in src.rglob("*.py"):
        if "adapters" in p.parts or p.name == "cli.py":
            continue
        for n in ast.walk(ast.parse(p.read_text())):
            mods = [a.name for a in n.names] if isinstance(n, ast.Import) else [n.module or ""] if isinstance(n, ast.ImportFrom) else []
            if any(m.startswith("infoparser.adapters") for m in mods):
                bad.append(str(p))
    assert not bad


# ---------- http ----------
def test_http_ingest_validates_body(svc):
    ok = handle(svc.inbox, {"url": "https://example.com/p", "context": "c"})
    assert set(ok) == {"id", "status", "duplicate"} and ok["status"] == "pending" and ok["duplicate"] is False
    assert handle(svc.inbox, {"url": "https://example.com/p"})["duplicate"] is True
    for bad in ({}, {"text": "a", "url": "https://x.org"}, {"url": "ftp://x"}, {"text": ""}, {"text": 5},
                {"text": "a", "context": 3}, "str", {"url": "javascript:1"}):
        with pytest.raises(ValueError):
            handle(svc.inbox, bad)


@pytest.fixture
def server(svc):
    s = IngestServer(svc.cfg, port=0)
    t = threading.Thread(target=s.serve_forever, daemon=True)
    t.start()
    yield s
    s.shutdown()
    s.server_close()
    t.join(5)
    assert not t.is_alive()


def req(s, method, path, body=None, headers=None, token=True):
    c = http.client.HTTPConnection("127.0.0.1", s.server_address[1], timeout=10)
    h = {"Authorization": f"Bearer {s.token}"} if token is True else ({"X-Token": token} if token else {})
    c.request(method, path, body=body, headers={**h, **(headers or {})})
    r = c.getresponse()
    data = r.read()
    c.close()
    try:
        return r.status, json.loads(data), dict(r.getheaders())
    except ValueError:
        return r.status, data, dict(r.getheaders())


def test_http_server_auth_routes_and_errors(server, svc):
    assert server.server_address[0] == "127.0.0.1"
    tok = Path(svc.cfg.home / "http_token")
    assert tok.read_text().strip() == server.token and (tok.stat().st_mode & 0o777) == 0o600
    assert load_token(svc.cfg) == server.token
    J = {"Content-Type": "application/json"}
    assert req(server, "POST", "/v1/inbox", b"{}", J, token=None)[0] == 401
    assert req(server, "POST", "/v1/inbox", b"{}", J, token="wrong")[0] == 401
    s, b, h = req(server, "POST", "/v1/inbox", json.dumps({"text": "hello via http"}).encode(), J)
    assert s == 200 and b["status"] == "pending" and "Access-Control-Allow-Origin" not in h
    s2, b2, _ = req(server, "POST", "/v1/inbox", json.dumps({"text": "x2"}).encode(), J, token=server.token)  # X-Token path
    assert s2 == 200
    g = req(server, "GET", f"/v1/inbox/{b['id']}", token=server.token)
    assert g[0] == 200 and g[1]["id"] == b["id"]
    assert req(server, "GET", "/v1/inbox/nope")[0] == 404
    assert req(server, "GET", "/v1/nothing")[0] == 404
    for bad in (b"{not json", b"[1]", b'{"text": 5}', b""):
        s, b, _ = req(server, "POST", "/v1/inbox", bad, J)
        assert s == 400 and "Traceback" not in json.dumps(b)
    big = b"x" * (svc.cfg.max_fetch_bytes + 1)
    c = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=10)
    c.putrequest("POST", "/v1/inbox")
    c.putheader("Authorization", f"Bearer {server.token}")
    c.putheader("Content-Length", str(len(big)))
    c.endheaders()
    assert c.getresponse().status == 413
    c.close()
    assert req(server, "OPTIONS", "/v1/inbox", token=None)[0] in (401, 404, 405, 501)


def test_http_file_upload_raw_and_multipart(server, svc):
    s, b, _ = req(server, "POST", "/v1/inbox", PNG, {"Content-Type": "image/png", "X-Filename": "../../evil name.png"})
    assert s == 200
    row = svc.inbox.get(b["id"])
    assert row["original_filename"] == "evil name.png" and svc.blobs.exists(row["blob_sha256"])
    bd = "BOUND"
    body = (f'--{bd}\r\nContent-Disposition: form-data; name="context"\r\n\r\nfrom form\r\n'
            f'--{bd}\r\nContent-Disposition: form-data; name="file"; filename="n.md"\r\n'
            f'Content-Type: text/markdown\r\n\r\n# multipart note\r\n--{bd}--\r\n').encode()
    s, b, _ = req(server, "POST", "/v1/inbox", body, {"Content-Type": f"multipart/form-data; boundary={bd}"})
    assert s == 200
    row = svc.inbox.get(b["id"])
    assert row["original_filename"] == "n.md" and row["user_context"] == "from form"


def test_http_refuses_nonloopback_without_explicit_token(svc):
    svc.cfg.http_bind = "0.0.0.0"
    with pytest.raises(ValueError):
        IngestServer(svc.cfg, port=0)
    svc.cfg.http_token = "explicit-token"
    s = IngestServer(svc.cfg, port=0)
    assert s.token == "explicit-token"
    s.server_close()


def test_cli_import_telegram_and_adapters_list(tmp_path):
    import subprocess, sys
    env = {**os.environ, "INFOPARSER_HOME": str(tmp_path / "h")}
    run = lambda *a: subprocess.run([sys.executable, "-m", "infoparser.cli", *a], env=env, capture_output=True, text=True, timeout=60)
    assert "telegram_export" in run("adapters", "list").stdout
    r1 = run("import-telegram", str(FIX / "result.json"))
    assert r1.returncode == 0 and "submitted 7" in r1.stdout, r1.stdout + r1.stderr
    assert "submitted 0, duplicates 7" in run("import-telegram", str(FIX / "result.json")).stdout
