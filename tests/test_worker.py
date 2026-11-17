import pytest

from pith.config import load_config
from pith.inbox.service import Inbox
from pith.jobs import JobQueue
from pith.store.blobs import BlobStore
from pith.store.db import connect, migrate
from pith.worker import Failed, NeedsClarification, Processed, Worker


def expire(conn):
    conn.execute("UPDATE jobs SET lease_expires_at='2000-01-01T00:00:00Z'")


class Crash(BaseException):
    pass


@pytest.fixture
def env(tmp_path):
    cfg = load_config(env={"PITH_HOME": str(tmp_path)})
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
    lvl = inbox.conn.execute("SELECT status FROM processing_events WHERE stage='retry'").fetchone()[0]
    assert lvl == "warning"
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


def test_outcome_is_atomic(env, monkeypatch):
    inbox, q, _ = env
    r = inbox.submit(adapter="t", text="x")
    w = Worker(inbox.conn, inbox, q, lambda i: Processed())
    real = inbox.set_status

    def boom(id, status, error=None):
        if status == "processed":
            raise RuntimeError("fault")
        return real(id, status, error)

    monkeypatch.setattr(inbox, "set_status", boom)
    with pytest.raises(RuntimeError):
        w.run_once()
    assert q.conn.execute("SELECT state FROM jobs").fetchone()[0] == "running"
    assert inbox.get(r.id)["status"] == "processing"
    assert "processed" not in events(inbox, r.id)


def test_stale_completion_is_ignored(env):
    inbox, q, _ = env
    r = inbox.submit(adapter="t", text="x")
    a = q.claim("A")
    expire(inbox.conn)
    b = q.claim("B")
    assert b.id == a.id
    assert q.complete(a.id, "A") is False
    assert q.fail(a.id, "late", "A") == "stale"
    assert q.conn.execute("SELECT state, worker_id FROM jobs").fetchone()[:] == ("running", "B")
    # via worker: A finishes late, must not touch inbox
    inbox.set_status(r.id, "processing")
    wa = Worker(inbox.conn, inbox, q, lambda i: Processed(), worker_id="A")
    wa._finish(a, Processed())
    assert inbox.get(r.id)["status"] == "processing"
    assert "stale_completion" in events(inbox, r.id)
    assert q.complete(b.id, "B") is True


def test_lease_expiry_events(env):
    inbox, q, cfg = env
    r = inbox.submit(adapter="t", text="x")
    q.claim("A")
    expire(inbox.conn)
    q.reclaim_expired()
    ev = inbox.conn.execute("SELECT stage, status FROM processing_events WHERE inbox_id=?", (r.id,)).fetchall()
    assert [tuple(e) for e in ev] == [("lease_expired", "warning")]
    inbox.conn.execute("UPDATE jobs SET attempts=?", (cfg.max_attempts,))
    q.claim("A")  # attempts now max+1 running
    inbox.conn.execute("UPDATE jobs SET state='running', lease_expires_at='2000-01-01T00:00:00Z'")
    q.reclaim_expired()
    assert inbox.get(r.id)["status"] == "failed"
    last = inbox.conn.execute("SELECT stage, status FROM processing_events ORDER BY id DESC").fetchone()
    assert tuple(last) == ("dead", "error")


def test_heartbeat_keeps_lease_during_processing(env):
    import time
    inbox, q, _ = env
    inbox.submit(adapter="t", text="x")
    seen = []

    def slow(iid):
        first = q.conn.execute("SELECT lease_expires_at FROM jobs").fetchone()[0]
        end = time.time() + 4
        while time.time() < end:
            cur = q.conn.execute("SELECT lease_expires_at FROM jobs").fetchone()[0]
            if cur != first:
                seen.append(cur)
                break
            time.sleep(0.05)
        return Processed()

    w = Worker(inbox.conn, inbox, q, slow)
    w.heartbeat_seconds = 0.2
    assert w.run_once()
    assert seen


def test_run_forever_survives_operational_error(env):
    import sqlite3
    import threading
    inbox, q, _ = env
    stop, calls = threading.Event(), []
    w = Worker(inbox.conn, inbox, q, lambda i: Processed())

    def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise sqlite3.OperationalError("locked")
        stop.set()
        return False

    w.run_once = flaky
    w.run_forever(poll_seconds=0.01, stop=stop)
    assert len(calls) == 2
