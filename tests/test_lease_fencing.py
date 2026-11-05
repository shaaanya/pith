"""A worker that lost its lease while processing writes nothing (no second source, no orphans)."""
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
