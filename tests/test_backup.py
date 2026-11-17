import hashlib
import io
import json
import os
import sqlite3
import tarfile
import threading
import time
from pathlib import Path

import pytest

from pith import backup
from pith.config import load_config
from pith.pipeline import runner
from pith.retrieval.ask import ask
from pith.retrieval.search import search
from pith.services import build
from pith.store.knowledge import get_item

NOTES = ["Quokkas are small marsupials from Australia. They live on Rottnest Island.",
         "Sourdough needs a long fermentation and a hot oven for good crust.",
         "Rust ownership rules prevent data races at compile time."]


def load(svc, notes=NOTES):
    for t in notes:
        runner.process(svc, svc.inbox.submit(adapter="t", text=t).id)
    svc.inbox.submit(adapter="t", file=b"%PDF-binary-ish blob \x00\x01", filename="x.bin")


def other(tmp_path, name="restored"):
    return load_config(env={"PITH_HOME": str(tmp_path / name)})


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
    from pith.services import build as b
    w = b(svc.cfg)

    done = []

    def writer():
        i = 0
        while not stop.is_set():
            try:
                runner.process(w, w.inbox.submit(adapter="t", text=f"concurrent writer note {i} unique{i}").id)
            except Exception as e:  # noqa: BLE001
                errs.append(e)
                return
            i += 1
            done.append(i)
    t = threading.Thread(target=writer, daemon=True)
    t.start()
    time.sleep(0.3)
    before = len(done)
    archives = [backup.backup(svc.cfg, tmp_path / f"o{k}") for k in range(3)]
    progressed = len(done) - before
    stop.set()
    t.join(10)
    assert not errs and progressed > 0  # the writer really was writing while the backups ran
    for k, a in enumerate(archives):
        cfg2 = other(tmp_path, f"r{k}")
        backup.restore(a, cfg2.home)
        c = sqlite3.connect(cfg2.db_path)
        assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert c.execute("PRAGMA foreign_key_check").fetchall() == []
        with tarfile.open(a) as tf:
            m = json.load(tf.extractfile("manifest.json"))
            snap = tmp_path / f"snap{k}.db"
            snap.write_bytes(tf.extractfile("infoparser.db").read())  # the snapshot itself, not the restored copy
        sc = sqlite3.connect(snap)
        assert m["counts"]["inbox_items"] == sc.execute("SELECT count(*) FROM inbox_items").fetchone()[0]
        assert m["counts"]["knowledge_items"] == sc.execute("SELECT count(*) FROM knowledge_items").fetchone()[0]
        sc.close()
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
        if n == "infoparser.db":
            f = tmp_path / "n.db"
            f.write_bytes(d)
            c = sqlite3.connect(f)
            c.execute("PRAGMA user_version=99")
            c.commit()
            c.close()
            newer.raw = f.read_bytes()
            return newer.raw
        if n == "manifest.json":
            m = json.loads(d)  # manifest still claims the old version: the DB's own version decides
            m["files"]["infoparser.db"] = None
            return json.dumps(m).encode()
        return d
    # members are visited in archive order: manifest first, so patch its hash after the fact
    mod = rewrite(a, newer)
    mod = rewrite(mod, lambda n, d: json.dumps({**json.loads(d), "files": {**json.loads(d)["files"],
                  "infoparser.db": hashlib.sha256(newer.raw).hexdigest()}}).encode() if n == "manifest.json" else d)
    with pytest.raises(backup.RestoreError, match="newer"):
        backup.restore(mod, other(tmp_path).home)
    # an older archive: strip the v2/v3 additions by building a v1 database
    from pith.store.db import _migrations, _split
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


def _junk_home(svc):
    (svc.cfg.blobs_dir / "ab").mkdir(parents=True, exist_ok=True)
    (svc.cfg.blobs_dir / "ab" / ".DS_Store").write_bytes(b"junk")
    v = svc.cfg.vault_dir
    (v / ".obsidian/plugins/x").mkdir(parents=True, exist_ok=True)
    (v / ".DS_Store").write_bytes(b"junk")
    (v / ".obsidian/plugins/x/main.js").write_text("legit")
    (v / "notes.md").write_text("my notes")


def test_junk_files_do_not_break_backup_and_legit_nested_vault_files_roundtrip(svc, tmp_path):
    load(svc)
    _junk_home(svc)
    a = backup.backup(svc.cfg, tmp_path / "o")
    assert backup.verify(a)["blob_count"] >= 1
    cfg2 = other(tmp_path)
    backup.restore(a, cfg2.home)
    assert (cfg2.vault_dir / ".obsidian/plugins/x/main.js").read_text() == "legit"
    assert (cfg2.vault_dir / "notes.md").read_text() == "my notes"
    assert not list(cfg2.home.rglob(".DS_Store"))


def test_corrupted_live_blob_fails_the_backup_and_leaves_no_archive(svc, tmp_path):
    load(svc)
    sha = svc.conn.execute("SELECT blob_sha256 FROM inbox_items WHERE blob_sha256 IS NOT NULL").fetchone()[0]
    svc.blobs.path(sha).write_bytes(b"bit rot")
    out = tmp_path / "o"
    with pytest.raises(backup.RestoreError, match="verification failed"):
        backup.backup(svc.cfg, out)
    assert not list(out.glob("*"))


def test_archive_mode_is_0600(svc, tmp_path):
    load(svc)
    a = backup.backup(svc.cfg, tmp_path / "o")
    assert (a.stat().st_mode & 0o777) == 0o600 and not list(a.parent.glob("*.part"))


def _snapshot_home(cfg):
    c = sqlite3.connect(cfg.db_path)
    assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    counts = [c.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in ("inbox_items", "knowledge_items", "segments")]
    c.close()
    return counts, sorted(p.name for p in cfg.blobs_dir.rglob("*") if p.is_file())


def _new_archive(tmp_path):
    cfg = other(tmp_path, "src")
    s = build(cfg)
    load(s, ["Entirely different content about volcanoes and magma chambers."])
    s.conn.close()
    return backup.backup(cfg, tmp_path / "srcbk")


@pytest.mark.parametrize("n,exc", [(1, OSError), (2, OSError), (3, OSError), (4, OSError), (3, KeyboardInterrupt)])
def test_force_restore_failure_mid_swap_leaves_old_home_intact(svc, tmp_path, monkeypatch, n, exc):
    load(svc)
    svc.conn.close()
    before = _snapshot_home(svc.cfg)
    arc = _new_archive(tmp_path)
    real, calls = os.replace, []

    def flaky(a, b, *x, **k):
        calls.append(1)
        if len(calls) == n:
            raise exc("injected")
        return real(a, b, *x, **k)
    monkeypatch.setattr(backup.os, "replace", flaky)
    with pytest.raises(exc):
        backup.restore(arc, svc.cfg.home, force=True)
    monkeypatch.undo()
    assert _snapshot_home(svc.cfg) == before
    assert not list(svc.cfg.home.glob(".pre-restore*")) and not list(svc.cfg.home.glob(".restore-stage*"))


def test_force_restore_success_leaves_no_temp_dirs(svc, tmp_path):
    load(svc)
    svc.conn.close()
    backup.restore(_new_archive(tmp_path), svc.cfg.home, force=True)
    assert not list(svc.cfg.home.glob(".pre-restore*")) and not list(svc.cfg.home.glob(".restore-stage*"))
    c = sqlite3.connect(svc.cfg.db_path)
    assert c.execute("SELECT count(*) FROM knowledge_items WHERE body LIKE '%volcano%'").fetchone()[0] >= 1


def test_restore_refused_while_run_lock_is_held(svc, tmp_path):
    import fcntl
    load(svc)
    svc.conn.close()
    before = _snapshot_home(svc.cfg)
    arc = _new_archive(tmp_path)
    held = open(svc.cfg.home / "run.lock", "a+")
    fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        with pytest.raises(backup.RestoreError, match="running"):
            backup.restore(arc, svc.cfg.home, force=True)
    finally:
        held.close()
    assert _snapshot_home(svc.cfg) == before


def test_manifest_types_validated_and_blob_prefix_and_caps(svc, tmp_path, monkeypatch):
    load(svc)
    a = backup.backup(svc.cfg, tmp_path / "o")
    for patch in ({"files": ["x"]}, {"schema_version": "abc"}, {"files": {"infoparser.db": 5}}, {"counts": 3}):
        def f(n, d, patch=patch):
            return json.dumps({**json.loads(d), **patch}).encode() if n == "manifest.json" else d
        with pytest.raises(backup.RestoreError):
            backup.verify(rewrite(a, f))
    wrong = tmp_path / "wrong.tar.gz"
    sha = "ab" + "c" * 62
    with tarfile.open(wrong, "w:gz") as t:
        ti = tarfile.TarInfo(f"blobs/zz/yy/{sha}")
        ti.size = 1
        t.addfile(ti, io.BytesIO(b"x"))
    with pytest.raises(backup.RestoreError):
        backup.verify(wrong)
    monkeypatch.setattr(backup, "MAX_MEMBERS", 2)
    with pytest.raises(backup.RestoreError, match="too many"):
        backup.verify(a)
    monkeypatch.setattr(backup, "MAX_MEMBERS", 10**6)
    monkeypatch.setattr(backup, "MAX_TOTAL_BYTES", 100)
    with pytest.raises(backup.RestoreError, match="too large"):
        backup.verify(a)
