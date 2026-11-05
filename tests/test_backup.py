import hashlib
import io
import json
import sqlite3
import tarfile
import threading
import time
from pathlib import Path

import pytest

from infoparser import backup
from infoparser.config import load_config
from infoparser.pipeline import runner
from infoparser.retrieval.ask import ask
from infoparser.retrieval.search import search
from infoparser.services import build
from infoparser.store.knowledge import get_item

NOTES = ["Quokkas are small marsupials from Australia. They live on Rottnest Island.",
         "Sourdough needs a long fermentation and a hot oven for good crust.",
         "Rust ownership rules prevent data races at compile time."]


def load(svc, notes=NOTES):
    for t in notes:
        runner.process(svc, svc.inbox.submit(adapter="t", text=t).id)
    svc.inbox.submit(adapter="t", file=b"%PDF-binary-ish blob \x00\x01", filename="x.bin")


def other(tmp_path, name="restored"):
    return load_config(env={"INFOPARSER_HOME": str(tmp_path / name)})


def rewrite(archive: Path, fn) -> Path:
    """Rebuild an archive, letting fn(name, data)->data|None alter/drop members."""
    out = archive.with_name("mod-" + archive.name)
    with tarfile.open(archive) as src, tarfile.open(out, "w:gz") as dst:
        for m in src.getmembers():
            data = src.extractfile(m).read() if m.isfile() else None
            if m.isfile():
                data = fn(m.name, data)
                if data is None:
                    continue
                m.size = len(data)
                dst.addfile(m, io.BytesIO(data))
            else:
                dst.addfile(m)
    return out


def test_backup_restore_roundtrip_search_ask_show_identical(svc, tmp_path):
    load(svc)
    a = backup.backup(svc.cfg, tmp_path / "out")
    assert a.name.endswith(".tar.gz") and a.is_file()
    cfg2 = other(tmp_path)
    backup.restore(a, cfg2.home)
    s2 = build(cfg2)
    for q in ("quokkas", "sourdough crust", "ownership"):
        r1, r2 = search(svc, q), search(s2, q)
        assert [(h.item_id, h.snippet, h.score, h.locator) for h in r1] == [(h.item_id, h.snippet, h.score, h.locator) for h in r2]
        assert r1
    a1, a2 = ask(svc, "where do quokkas live").to_dict(), ask(s2, "where do quokkas live").to_dict()
    assert a1["mode"] == a2["mode"] == "retrieval-only" and a1 == a2
    for r in svc.conn.execute("SELECT id FROM knowledge_items"):
        assert get_item(svc.conn, r["id"]) == get_item(s2.conn, r["id"])
    assert s2.conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert {r["blob_sha256"] for r in svc.conn.execute("SELECT blob_sha256 FROM inbox_items WHERE blob_sha256 IS NOT NULL")} \
        <= {p.name for p in cfg2.blobs_dir.rglob("*") if p.is_file()}


def test_manifest_contents_and_secrets_excluded(svc, tmp_path):
    load(svc)
    (svc.cfg.home / "http_token").write_text("secret-token")
    a = backup.backup(svc.cfg, tmp_path / "o")
    with tarfile.open(a) as t:
        names = t.getnames()
        m = json.load(t.extractfile("manifest.json"))
    assert {"schema_version", "created_at", "counts", "blob_count", "app_version"} <= set(m)
    assert m["counts"]["knowledge_items"] >= 3 and m["blob_count"] >= 1
    assert not any("http_token" in n for n in names)


def test_restore_refuses_nonempty_home_and_force_replaces(svc, tmp_path):
    load(svc)
    a = backup.backup(svc.cfg, tmp_path / "o")
    cfg2 = other(tmp_path)
    s2 = build(cfg2)  # creates a non-empty home
    s2.inbox.submit(adapter="t", text="local only note")
    s2.conn.close()
    with pytest.raises(backup.RestoreError, match="not empty"):
        backup.restore(a, cfg2.home)
    assert cfg2.db_path.exists()
    backup.restore(a, cfg2.home, force=True)
    s3 = build(cfg2)
    assert s3.conn.execute("SELECT count(*) FROM inbox_items WHERE payload_text='local only note'").fetchone()[0] == 0
    assert s3.conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_backup_consistent_while_a_writer_is_writing(svc, tmp_path):
    load(svc)
    stop, errs = threading.Event(), []
    from infoparser.services import build as b
    w = b(svc.cfg)

    def writer():
        i = 0
        while not stop.is_set():
            try:
                runner.process(w, w.inbox.submit(adapter="t", text=f"concurrent writer note {i} unique{i}").id)
            except Exception as e:  # noqa: BLE001
                errs.append(e)
                return
            i += 1
    t = threading.Thread(target=writer, daemon=True)
    t.start()
    time.sleep(0.3)
    archives = [backup.backup(svc.cfg, tmp_path / f"o{k}") for k in range(3)]
    stop.set()
    t.join(10)
    assert not errs
    for k, a in enumerate(archives):
        cfg2 = other(tmp_path, f"r{k}")
        backup.restore(a, cfg2.home)
        c = sqlite3.connect(cfg2.db_path)
        assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert c.execute("PRAGMA foreign_key_check").fetchall() == []
        with tarfile.open(a) as tf:
            m = json.load(tf.extractfile("manifest.json"))
        assert m["counts"]["inbox_items"] == c.execute("SELECT count(*) FROM inbox_items").fetchone()[0]
        assert m["counts"]["knowledge_items"] == c.execute("SELECT count(*) FROM knowledge_items").fetchone()[0]
        # FTS and items agree inside the snapshot
        assert c.execute("SELECT count(*) FROM items_fts").fetchone()[0] == \
            c.execute("SELECT count(*) FROM knowledge_items WHERE deleted_at IS NULL").fetchone()[0]


def test_corrupted_blob_detected_on_restore_and_nothing_written(svc, tmp_path):
    load(svc)
    a = backup.backup(svc.cfg, tmp_path / "o")
    bad = rewrite(a, lambda n, d: d + b"X" if n.startswith("blobs/") else d)
    cfg2 = other(tmp_path)
    with pytest.raises(backup.RestoreError, match="blob"):
        backup.restore(bad, cfg2.home)
    assert not cfg2.home.exists()
    with pytest.raises(backup.RestoreError, match="blob"):
        backup.verify(bad)
    missing = rewrite(a, lambda n, d: None if n.startswith("blobs/") else d)
    with pytest.raises(backup.RestoreError):
        backup.verify(missing)
    assert backup.verify(a)["schema_version"] >= 3


def test_corrupted_db_in_backup_detected(svc, tmp_path):
    load(svc)
    a = backup.backup(svc.cfg, tmp_path / "o")
    bad = rewrite(a, lambda n, d: d[:4096] + b"\xff" * 2000 + d[6096:] if n == "infoparser.db" else d)
    with pytest.raises(backup.RestoreError):
        backup.restore(bad, other(tmp_path).home)


def _evil(tmp_path, name, kind="file", data=b"pwn"):
    out = tmp_path / f"evil-{abs(hash(name))}.tar.gz"
    with tarfile.open(out, "w:gz") as t:
        ti = tarfile.TarInfo(name)
        if kind == "symlink":
            ti.type, ti.linkname = tarfile.SYMTYPE, "/etc/passwd"
            t.addfile(ti)
        elif kind == "hardlink":
            ti.type, ti.linkname = tarfile.LNKTYPE, "infoparser.db"
            t.addfile(ti)
        else:
            ti.size = len(data)
            t.addfile(ti, io.BytesIO(data))
    return out


@pytest.mark.parametrize("name,kind", [("../escape.txt", "file"), ("/tmp/abs-escape.txt", "file"),
                                       ("blobs/../../escape.txt", "file"), ("blobs/ab/link", "symlink"),
                                       ("blobs/ab/hard", "hardlink"), ("evil/other.txt", "file"),
                                       ("blobs/..\\x", "file")])
def test_malicious_archive_rejected(tmp_path, name, kind):
    a = _evil(tmp_path, name, kind)
    home = tmp_path / "h"
    with pytest.raises(backup.RestoreError):
        backup.restore(a, home)
    assert not home.exists() and not (tmp_path / "escape.txt").exists() and not Path("/tmp/abs-escape.txt").exists()


def test_newer_schema_refused_older_migrated(svc, tmp_path):
    load(svc)
    a = backup.backup(svc.cfg, tmp_path / "o")

    def newer(n, d):
        if n == "manifest.json":
            m = json.loads(d)
            m["schema_version"] = 99
            return json.dumps(m).encode()
        return d
    with pytest.raises(backup.RestoreError, match="newer"):
        backup.restore(rewrite(a, newer), other(tmp_path).home)
    # an older archive: strip the v2/v3 additions by building a v1 database
    from infoparser.store.db import _migrations, _split
    v1 = tmp_path / "v1.db"
    c = sqlite3.connect(v1)
    for s in _split(_migrations()[0][1]):
        c.execute(s)
    c.execute("PRAGMA user_version=1")
    c.execute("INSERT INTO inbox_items(id,adapter,submitted_at,status,updated_at,payload_text) VALUES ('a','t','2026-01-01T00:00:00Z','new','2026-01-01T00:00:00Z','hi')")
    c.commit()
    c.close()
    raw = v1.read_bytes()

    def older(n, d):
        if n == "infoparser.db":
            return raw
        if n == "manifest.json":
            m = json.loads(d)
            m["schema_version"] = 1
            m["files"]["infoparser.db"] = hashlib.sha256(raw).hexdigest()
            return json.dumps(m).encode()
        return d
    old = rewrite(a, older)
    cfg2 = other(tmp_path, "migrated")
    backup.restore(old, cfg2.home, force=False)
    c = build(cfg2).conn
    assert c.execute("PRAGMA user_version").fetchone()[0] >= 3
    assert c.execute("SELECT payload_text FROM inbox_items WHERE id='a'").fetchone()[0] == "hi"
