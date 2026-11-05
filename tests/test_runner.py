from infoparser.pipeline import runner
from infoparser.worker import Failed, NeedsClarification, Processed

NOTE = "Retrieval augmented generation combines search with generation.\n\nChunking strategy matters a lot."


def test_runner_note_end_to_end_heuristic(svc):
    iid = svc.inbox.submit(adapter="t", text=NOTE).id
    assert isinstance(runner.process(svc, iid), Processed)
    row = svc.inbox.get(iid)
    assert row["source_id"] and row["content_type"] == "note"
    items = svc.conn.execute("SELECT * FROM knowledge_items WHERE source_id=? AND deleted_at IS NULL",
                             (row["source_id"],)).fetchall()
    assert items
    stages = {r["stage"] for r in svc.conn.execute("SELECT stage FROM processing_events WHERE inbox_id=?", (iid,))}
    assert {"detect", "extract", "chunk", "distill", "save"} <= stages
    # idempotent: reprocess does not duplicate live items
    runner.process(svc, iid)
    n = svc.conn.execute("SELECT count(*) FROM knowledge_items WHERE source_id=? AND deleted_at IS NULL",
                         (row["source_id"],)).fetchone()[0]
    assert n == len(items)
    assert svc.conn.execute("SELECT count(*) FROM sources").fetchone()[0] == 1


def test_runner_empty_text_fails_cleanly(svc):
    for kw in ({"text": "   "}, {"file": b""}):
        iid = svc.inbox.submit(adapter="t", **kw).id
        out = runner.process(svc, iid)
        assert isinstance(out, (NeedsClarification, Failed))
        row = svc.inbox.get(iid)
        if row["blob_sha256"]:
            assert svc.blobs.exists(row["blob_sha256"])
        assert svc.conn.execute("SELECT count(*) FROM knowledge_items").fetchone()[0] == 0


def test_runner_non_utf8_file_decoded_with_replacement(svc):
    iid = svc.inbox.submit(adapter="t", file=b"caf\xe9 culture is a zebra topic. " * 3, filename="a.txt").id
    assert isinstance(runner.process(svc, iid), Processed)
    seg = svc.conn.execute("SELECT text FROM segments").fetchone()[0]
    assert "�" in seg and "zebra" in seg


def test_runner_unknown_type_needs_clarification(svc):
    iid = svc.inbox.submit(adapter="t", file=b"%PDF-1.4 x", filename="a.pdf").id
    out = runner.process(svc, iid)
    assert isinstance(out, NeedsClarification) and "pdf" in out.reason
    assert svc.blobs.exists(svc.inbox.get(iid)["blob_sha256"])


def test_runner_extractor_exception_is_failed_with_event(svc, monkeypatch):
    from infoparser.pipeline.extractors import base
    monkeypatch.setitem(base.EXTRACTORS, "note", lambda ctx: 1 / 0)
    iid = svc.inbox.submit(adapter="t", text=NOTE).id
    out = runner.process(svc, iid)
    assert isinstance(out, Failed) and "ZeroDivisionError" in out.error
    assert svc.conn.execute("SELECT count(*) FROM processing_events WHERE inbox_id=? AND status='error'",
                            (iid,)).fetchone()[0] == 1
