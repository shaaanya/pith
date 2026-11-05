import pytest

from infoparser.config import load_config
from infoparser.inbox.service import Inbox
from infoparser.jobs import JobQueue
from infoparser.store.blobs import BlobStore
from infoparser.store.db import connect, migrate
from infoparser.worker import Failed, NeedsClarification, Processed, Worker


class Crash(BaseException):
    pass


@pytest.fixture
def env(tmp_path):
    cfg = load_config(env={"INFOPARSER_HOME": str(tmp_path)})
    conn = connect(cfg.db_path)
    migrate(conn)
    inbox = Inbox(conn, BlobStore(cfg.blobs_dir), cfg)
    return inbox, JobQueue(conn, cfg), cfg


def events(inbox, iid):
    return [r["stage"] for r in inbox.conn.execute(
        "SELECT stage FROM processing_events WHERE inbox_id=? ORDER BY id", (iid,))]


def test_run_once_idle(env):
    inbox, q, _ = env
    assert Worker(inbox.conn, inbox, q, lambda i: Processed()).run_once() is False


def test_worker_maps_outcomes(env):
    inbox, q, _ = env
    ids = {k: inbox.submit(adapter="t", text=k).id for k in ("ok", "clar", "fail", "boom")}
    by_id = {v: k for k, v in ids.items()}

    def proc(iid):
        k = by_id[iid]
        if k == "ok":
            return Processed()
        if k == "clar":
            return NeedsClarification("what is this?")
        if k == "fail":
            return Failed("bad")
        raise RuntimeError("kaboom")

    w = Worker(inbox.conn, inbox, q, proc)
    while w.run_once():
        pass
    assert inbox.get(ids["ok"])["status"] == "processed"
    c = inbox.get(ids["clar"])
    assert c["status"] == "needs_clarification" and c["error"] == "what is this?"
    for k, err in (("fail", "bad"), ("boom", "kaboom")):
        row = inbox.get(ids[k])
        assert row["status"] == "pending" and err in row["error"]  # retry scheduled
    assert events(inbox, ids["ok"]) == ["claimed", "processed"]
    assert "retry" in events(inbox, ids["boom"])


def test_worker_dead_marks_inbox_failed(env):
    inbox, q, cfg = env
    r = inbox.submit(adapter="t", text="x")
    w = Worker(inbox.conn, inbox, q, lambda i: Failed("nope"))
    for _ in range(cfg.max_attempts):
        inbox.conn.execute("UPDATE jobs SET run_after='2000-01-01T00:00:00Z' WHERE state='pending'")
        assert w.run_once()
    row = inbox.get(r.id)
    assert row["status"] == "failed" and row["error"] == "nope"
    assert "dead" in events(inbox, r.id)


def test_worker_crash_midjob_resumes_once(env):
    inbox, q, _ = env
    r = inbox.submit(adapter="t", text="x")
    effects = []

    def crashing(iid):
        raise Crash

    with pytest.raises(Crash):
        Worker(inbox.conn, inbox, q, crashing, worker_id="w1").run_once()
    assert inbox.get(r.id)["status"] == "processing"
    assert Worker(inbox.conn, inbox, q, lambda i: effects.append(i) or Processed(),
                  worker_id="w2").run_once() is False  # lease still live
    inbox.conn.execute("UPDATE jobs SET lease_expires_at='2000-01-01T00:00:00Z'")
    w2 = Worker(inbox.conn, inbox, q, lambda i: effects.append(i) or Processed(), worker_id="w2")
    assert w2.run_once() is True
    assert w2.run_once() is False
    assert effects == [r.id]
    assert inbox.get(r.id)["status"] == "processed"
    assert q.conn.execute("SELECT state FROM jobs").fetchone()[0] == "done"


def test_run_forever_stops(env):
    import threading
    inbox, q, _ = env
    inbox.submit(adapter="t", text="x")
    stop, seen = threading.Event(), []
    w = Worker(inbox.conn, inbox, q, lambda i: seen.append(i) or stop.set() or Processed())
    w.run_forever(poll_seconds=0.01, stop=stop)
    assert len(seen) == 1
