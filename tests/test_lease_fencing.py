"""A worker that lost its lease while processing writes nothing (no second source, no orphans)."""
from infoparser import jobs
from infoparser.pipeline import runner
from infoparser.services import build
from infoparser.worker import Worker

NOTE = ("Retrieval augmented generation combines search with generation.\n\n"
        "Chunking strategy matters a lot for retrieval quality.")


def _worker(svc, wid):
    return Worker(svc.conn, svc.inbox, svc.queue, lambda i: runner.process(svc, i), worker_id=wid)


def test_worker_that_lost_its_lease_writes_nothing(svc, monkeypatch):
    """A stalls inside distill, its lease expires, B reclaims and finishes; then A resumes."""
    iid = svc.inbox.submit(adapter="t", text=NOTE).id
    svc_a = build(svc.cfg)  # a second process on the same home
    real, state = runner.distill, {"inner": False}

    def stalled(*args, **kwargs):
        if not state["inner"]:  # A's call: its lease runs out and B takes over completely
            state["inner"] = True
            svc.conn.execute("UPDATE jobs SET lease_expires_at='2000-01-01T00:00:00+00:00'")
            assert _worker(svc, "B").run_once()
        return real(*args, **kwargs)

    monkeypatch.setattr(runner, "distill", stalled)
    assert _worker(svc_a, "A").run_once()

    def q(sql):
        return svc.conn.execute(sql).fetchone()[0]

    assert q("SELECT count(*) FROM sources") == 1
    row = svc.inbox.get(iid)
    live = q("SELECT count(*) FROM knowledge_items WHERE deleted_at IS NULL")
    assert live
    assert q("SELECT count(DISTINCT source_id) FROM knowledge_items"
             " WHERE deleted_at IS NULL") == 1
    assert q(f"SELECT count(*) FROM knowledge_items WHERE source_id='{row['source_id']}'"
             " AND deleted_at IS NULL") == live
    assert q("SELECT count(*) FROM relations") == 0
    assert q(f"SELECT count(*) FROM processing_events WHERE inbox_id='{iid}' AND status='error'")


EXPIRED = "2000-01-01T00:00:00+00:00"
OLD = "The bridge opened in 1901 after four years of construction by local masons."
NEWER = "The museum holds pottery and textiles gathered from many regional excavations."


def test_stale_reprocess_does_not_overwrite_newer_content(svc, monkeypatch):
    """Reprocess after the page changed: A fetched OLD and stalls; B saves NEW; A must not win."""
    iid = svc.inbox.submit(adapter="t", text=OLD).id
    assert _worker(svc, "first").run_once()  # the source exists, so a reprocess has a source_id
    svc.inbox.retry(iid)
    svc_a = build(svc.cfg)
    fetched, real = [], runner.distill

    def pieces(_ex):
        fetched.append(1)
        return [(OLD if len(fetched) == 1 else NEWER, None)]  # A sees OLD, B sees the new page

    def stalled(*args, **kwargs):
        if len(fetched) == 1:
            svc.conn.execute(f"UPDATE jobs SET lease_expires_at='{EXPIRED}'")
            assert _worker(svc, "B").run_once()
        return real(*args, **kwargs)

    monkeypatch.setattr(runner, "_pieces", pieces)
    monkeypatch.setattr(runner, "distill", stalled)
    assert _worker(svc_a, "A").run_once()
    texts = [r[0] for r in svc.conn.execute("SELECT text FROM segments")]
    assert texts == [NEWER]
    job = svc.conn.execute("SELECT state, worker_id FROM jobs ORDER BY id DESC").fetchone()
    assert tuple(job) == ("done", "B")


def test_first_run_loser_does_not_block_the_real_lease_holder(svc, monkeypatch):
    """A (lease lost) must write nothing, so B, the current holder, can still save."""
    iid = svc.inbox.submit(adapter="t", text=NOTE).id
    svc_b = build(svc.cfg)
    real, held = runner.distill, {}

    def stalled(*args, **kwargs):
        if not held:
            svc.conn.execute(f"UPDATE jobs SET lease_expires_at='{EXPIRED}'")
            held["job"] = svc_b.queue.claim("B")  # B now holds the lease but has not saved yet
        return real(*args, **kwargs)

    monkeypatch.setattr(runner, "distill", stalled)
    assert _worker(svc, "A").run_once()
    # the loser wrote nothing
    assert svc.conn.execute("SELECT count(*) FROM sources").fetchone()[0] == 0
    job = held["job"]
    tok = jobs.current.set((job.id, "B", job.attempts))
    try:
        out = runner.process(svc_b, iid)
    finally:
        jobs.current.reset(tok)
    assert type(out).__name__ == "Processed"
    assert svc.conn.execute("SELECT count(*) FROM sources").fetchone()[0] == 1


def test_heartbeat_of_a_stale_worker_does_not_extend_the_new_owners_lease(svc):
    """heartbeat is filtered on the worker id."""
    svc.inbox.submit(adapter="t", text=NOTE)
    job = svc.queue.claim("B")
    svc.conn.execute(f"UPDATE jobs SET lease_expires_at='{EXPIRED}' WHERE id=?", (job.id,))
    svc.queue.heartbeat(job.id, "A")
    assert svc.conn.execute("SELECT lease_expires_at FROM jobs").fetchone()[0] == EXPIRED
    svc.queue.heartbeat(job.id, "B")
    assert svc.conn.execute("SELECT lease_expires_at FROM jobs").fetchone()[0] != EXPIRED
