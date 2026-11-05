import pytest

from infoparser.config import load_config
from infoparser.inbox.service import Inbox
from infoparser.store.blobs import BlobStore
from infoparser.store.db import connect, migrate


@pytest.fixture
def inbox(tmp_path):
    cfg = load_config(env={"INFOPARSER_HOME": str(tmp_path)})
    conn = connect(cfg.db_path)
    migrate(conn)
    return Inbox(conn, BlobStore(cfg.blobs_dir), cfg)


def count(inbox, table):
    return inbox.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_submit_persists_before_return(inbox):
    r = inbox.submit(adapter="t", file=b"data", filename="a.bin", user_context="ctx")
    row = inbox.get(r.id)
    assert row["status"] == "pending" and row["kind_hint"] == "file"
    assert inbox.blobs.exists(row["blob_sha256"])
    jobs = inbox.conn.execute("SELECT * FROM jobs WHERE inbox_id=?", (r.id,)).fetchall()
    assert len(jobs) == 1 and jobs[0]["state"] == "pending"
    assert count(inbox, "sources") == 0  # no extraction
    assert r.duplicate_of is None and not r.requeued


def test_bare_url_vs_text(inbox):
    u = inbox.get(inbox.submit(adapter="t", text=" https://youtu.be/x ").id)
    assert u["kind_hint"] == "url" and u["platform"] == "youtube"
    assert u["canonical_url"] == "https://youtube.com/watch?v=x"
    t = inbox.get(inbox.submit(adapter="t", text="see https://a.com ok").id)
    assert t["kind_hint"] == "text" and t["canonical_url"] is None


def test_submit_duplicate_url_returns_existing_and_keeps_context(inbox):
    a = inbox.submit(adapter="t", text="https://example.com/p/?utm_source=x", user_context="first")
    b = inbox.submit(adapter="t", text="http://www.example.com/p", user_context="second")
    assert b.id == a.id and b.duplicate_of == a.id and not b.requeued
    ctx = inbox.get(a.id)["user_context"]
    assert "first" in ctx and "second" in ctx
    assert count(inbox, "inbox_items") == 1 and count(inbox, "jobs") == 1
    assert count(inbox, "provenance_log") == 1


def test_submit_same_file_hash_dedupes(inbox, tmp_path):
    f = tmp_path / "x.txt"
    f.write_bytes(b"same")
    a = inbox.submit(adapter="t", file=f, user_context="one")
    b = inbox.submit(adapter="t", file=b"same", user_context="two")
    assert b.duplicate_of == a.id and b.id == a.id
    assert "two" in inbox.get(a.id)["user_context"]
    assert count(inbox, "inbox_items") == 1


@pytest.mark.parametrize("state", ["failed", "needs_clarification"])
def test_resubmit_dead_requeues_with_new_context(inbox, state):
    a = inbox.submit(adapter="t", text="https://example.com/p", user_context="old")
    inbox.set_status(a.id, state, error="boom")
    inbox.conn.execute("UPDATE jobs SET state='failed' WHERE inbox_id=?", (a.id,))
    b = inbox.submit(adapter="t", text="https://example.com/p/", user_context="new hint")
    assert b.id == a.id and b.requeued and b.duplicate_of == a.id
    row = inbox.get(a.id)
    assert row["status"] == "pending" and row["error"] is None
    assert "old" in row["user_context"] and "new hint" in row["user_context"]
    assert count(inbox, "inbox_items") == 1
    pending = inbox.conn.execute("SELECT COUNT(*) FROM jobs WHERE state='pending'").fetchone()[0]
    assert pending == 1


def test_submit_neither_text_nor_file_raises(inbox):
    with pytest.raises(ValueError):
        inbox.submit(adapter="t")
    with pytest.raises(ValueError):
        inbox.submit(adapter="t", text="a", file=b"b")


def test_submit_is_atomic(inbox, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("job insert failed")

    monkeypatch.setattr(inbox, "_insert_job", boom)
    with pytest.raises(RuntimeError):
        inbox.submit(adapter="t", text="https://example.com/z")
    assert count(inbox, "inbox_items") == 0 and count(inbox, "jobs") == 0
    monkeypatch.undo()
    inbox.submit(adapter="t", text="https://example.com/z")  # not left locked
    assert count(inbox, "inbox_items") == 1


def test_retry_clarify_list_events(inbox):
    a = inbox.submit(adapter="t", text="hello")
    inbox.set_status(a.id, "needs_clarification", error="what?")
    inbox.clarify(a.id, "it is about X")
    row = inbox.get(a.id)
    assert row["status"] == "pending" and "it is about X" in row["user_context"]
    inbox.set_status(a.id, "failed", error="e")
    inbox.conn.execute("UPDATE jobs SET state='failed'")
    inbox.retry(a.id)
    assert inbox.get(a.id)["status"] == "pending"
    assert [r["id"] for r in inbox.list(status="pending")] == [a.id]
    assert inbox.list(status="failed") == []
    inbox.add_event(a.id, "detect", "info", "ok", {"k": 1}, model="m")
    ev = inbox.conn.execute("SELECT * FROM processing_events").fetchone()
    assert ev["stage"] == "detect" and ev["status"] == "info" and ev["model"] == "m"
    assert '"k": 1' in ev["detail"]
