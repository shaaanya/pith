import calendar
import threading
import time

import pytest

from infoparser.config import load_config
from infoparser.inbox.service import Inbox
from infoparser.jobs import JobQueue
from infoparser.store.blobs import BlobStore
from infoparser.store.db import connect, migrate


@pytest.fixture
def env(tmp_path):
    cfg = load_config(env={"INFOPARSER_HOME": str(tmp_path)})
    conn = connect(cfg.db_path)
    migrate(conn)
    inbox = Inbox(conn, BlobStore(cfg.blobs_dir), cfg)
    return inbox, JobQueue(conn, cfg), cfg


def expire(conn):
    conn.execute("UPDATE jobs SET lease_expires_at='2000-01-01T00:00:00Z'")


def due(conn):
    conn.execute("UPDATE jobs SET run_after='2000-01-01T00:00:00Z' WHERE state='pending'")


def test_claim_is_exclusive(env):
    inbox, q, _ = env
    inbox.submit(adapter="t", text="one")
    j = q.claim("w1")
    assert j and j.attempts == 1 and j.kind == "process"
    assert q.claim("w2") is None


def test_expired_lease_is_reclaimed(env):
    inbox, q, _ = env
    r = inbox.submit(adapter="t", text="one")
    j = q.claim("w1")
    assert q.reclaim_expired() == 0
    expire(q.conn)
    assert q.reclaim_expired() == 1
    j2 = q.claim("w2")
    assert j2.id == j.id and j2.inbox_id == r.id and j2.attempts == 2


def test_heartbeat_extends_lease(env):
    inbox, q, _ = env
    inbox.submit(adapter="t", text="one")
    j = q.claim("w1")
    expire(q.conn)
    q.heartbeat(j.id)
    assert q.reclaim_expired() == 0


def test_fail_backoff_then_dead_keeps_original(env):
    inbox, q, cfg = env
    r = inbox.submit(adapter="t", file=b"payload", filename="a.bin")
    sha = inbox.get(r.id)["blob_sha256"]
    for i in range(1, cfg.max_attempts + 1):
        j = q.claim("w1")
        assert j is not None
        res = q.fail(j.id, "boom")
        assert res == ("dead" if i == cfg.max_attempts else "retry")
        if res == "retry":
            ra = q.conn.execute("SELECT run_after FROM jobs").fetchone()[0]
            delay = calendar.timegm(time.strptime(ra, "%Y-%m-%dT%H:%M:%SZ")) - time.time()
            want = min(5 * 2 ** (i - 1), 3600)
            assert want - 2 <= delay <= want + 1  # exponential growth
            assert q.claim("w1") is None  # backed off
            due(q.conn)
    assert q.claim("w1") is None
    assert q.conn.execute("SELECT state, last_error FROM jobs").fetchone()[:] == ("failed", "boom")
    assert inbox.get(r.id)["blob_sha256"] == sha and inbox.blobs.exists(sha)


def test_enqueue_skips_when_live_job(env):
    inbox, q, _ = env
    r = inbox.submit(adapter="t", text="one")
    existing = q.conn.execute("SELECT id FROM jobs").fetchone()[0]
    assert q.enqueue(r.id) == existing
    j = q.claim("w1")
    q.complete(j.id)
    new = q.enqueue(r.id)
    assert new != existing and q.claim("w1").id == new


def test_concurrent_claims_threads(env):
    inbox, q, cfg = env
    for i in range(20):
        inbox.submit(adapter="t", text=f"item {i}")
    got, lock = [], threading.Lock()

    def work(n):
        queue = JobQueue(connect(cfg.db_path), cfg)
        while (j := queue.claim(f"w{n}")):
            with lock:
                got.append(j.id)

    ts = [threading.Thread(target=work, args=(n,)) for n in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(got) == 20 and len(set(got)) == 20


def test_backoff_is_capped(env):
    inbox, q, cfg = env
    cfg.max_attempts = 100
    inbox.submit(adapter="t", text="x")
    q.claim("w")
    q.conn.execute("UPDATE jobs SET attempts=50")
    assert q.fail(q.conn.execute("SELECT id FROM jobs").fetchone()[0], "e") == "retry"
    ra = q.conn.execute("SELECT run_after FROM jobs").fetchone()[0]
    assert calendar.timegm(time.strptime(ra, "%Y-%m-%dT%H:%M:%SZ")) - time.time() <= 3601
