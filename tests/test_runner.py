from pith.pipeline import runner
from pith.worker import Failed, NeedsClarification, Processed

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


def test_runner_unreadable_media_needs_clarification(svc):
    iid = svc.inbox.submit(adapter="t", file=b"ID3 x", filename="a.mp3").id
    out = runner.process(svc, iid)
    assert isinstance(out, NeedsClarification) and ("stream" in out.reason or "ffmpeg" in out.reason)
    assert svc.blobs.exists(svc.inbox.get(iid)["blob_sha256"])


def test_runner_extractor_exception_is_failed_with_event(svc, monkeypatch):
    from pith.pipeline.extractors import base
    monkeypatch.setitem(base.EXTRACTORS, "note", lambda ctx: 1 / 0)
    iid = svc.inbox.submit(adapter="t", text=NOTE).id
    out = runner.process(svc, iid)
    assert isinstance(out, Failed) and "ZeroDivisionError" in out.error
    assert svc.conn.execute("SELECT count(*) FROM processing_events WHERE inbox_id=? AND status='error'",
                            (iid,)).fetchone()[0] == 1


def test_runner_refreshes_source_and_content_types_match(svc):
    iid = svc.inbox.submit(adapter="t", text="def f():\n    return 1\n\nclass A: pass").id
    runner.process(svc, iid)
    row = svc.inbox.get(iid)
    src = svc.conn.execute("SELECT * FROM sources WHERE id=?", (row["source_id"],)).fetchone()
    assert row["content_type"] == src["content_type"] == "code"
    # edit via requeue with new context: profile hint must be accepted, source refreshed on reprocess
    svc.conn.execute("UPDATE inbox_items SET payload_text='# New title\n\nchanged body here' WHERE id=?", (iid,))
    runner.process(svc, iid)
    src2 = svc.conn.execute("SELECT * FROM sources WHERE id=?", (row["source_id"],)).fetchone()
    assert src2["title"] == "# New title".lstrip("# ") and src2["text_sha256"] != src["text_sha256"]
    assert src2["content_type"] == "note"
    assert svc.inbox.get(iid)["content_type"] == "note"


def test_runner_uses_profile_for_with_user_context(svc, monkeypatch):
    seen = {}
    real = runner.distill
    monkeypatch.setattr(runner, "distill", lambda *a, **k: (seen.update(k), real(*a, **k))[1])
    iid = svc.inbox.submit(adapter="t", text="Some list items here.", user_context="top 10 tools").id
    runner.process(svc, iid)
    assert seen["profile"] == "collection"


def test_runner_failed_keeps_original_error_if_event_write_fails(svc, monkeypatch):
    from pith.pipeline.extractors import base
    monkeypatch.setitem(base.EXTRACTORS, "note", lambda ctx: 1 / 0)
    real = runner._stage

    def stage(conn, iid, name, *a, **k):
        if name == "error":
            raise RuntimeError("db gone")
        return real(conn, iid, name, *a, **k)

    monkeypatch.setattr(runner, "_stage", stage)
    iid = svc.inbox.submit(adapter="t", text="hello world").id
    out = runner.process(svc, iid)
    assert isinstance(out, Failed) and "ZeroDivisionError" in out.error


def test_runner_no_extractor_branch(svc, monkeypatch):
    from pith.pipeline.extractors import base
    monkeypatch.delitem(base.EXTRACTORS, "note")
    iid = svc.inbox.submit(adapter="t", text="hello there").id
    out = runner.process(svc, iid)
    assert isinstance(out, NeedsClarification) and "no extractor available" in out.reason


LONG_CTX = "Telegram message 2026-01-02 from Alice Example / forwarded from Some Channel about animals and travel plans"
PASTE = "Quokkas are small marsupials from Australia and they live on Rottnest Island eating grass."


def wall_url(srv):
    return srv.base + "/wall"


def test_long_submit_context_never_becomes_content(svc):
    from stubs.http_fixture_server import FIXTURES, FixtureServer, Route
    with FixtureServer({"/wall": Route(FIXTURES / "login_wall.html")}) as srv:
        iid = svc.inbox.submit(adapter="t", text=wall_url(srv), user_context=LONG_CTX).id
        out = runner.process(svc, iid)
    assert isinstance(out, NeedsClarification) and "paste the text" in out.reason
    iid = svc.inbox.submit(adapter="t", text="   ", user_context=LONG_CTX).id  # telegram-style
    assert isinstance(runner.process(svc, iid), NeedsClarification)
    assert svc.conn.execute("SELECT count(*) FROM sources").fetchone()[0] == 0


def test_clarify_writes_event_and_context(svc):
    iid = svc.inbox.submit(adapter="t", text="   ").id
    svc.inbox.clarify(iid, PASTE)
    ev = svc.conn.execute("SELECT detail FROM processing_events WHERE inbox_id=? AND stage='clarified'", (iid,)).fetchone()
    assert ev["detail"] == PASTE and PASTE in svc.inbox.get(iid)["user_context"]


def test_clarification_text_becomes_user_supplied_source(svc):
    from stubs.http_fixture_server import FIXTURES, FixtureServer, Route
    from pith.worker import Processed
    with FixtureServer({"/wall": Route(FIXTURES / "login_wall.html")}) as srv:
        iid = svc.inbox.submit(adapter="t", text=wall_url(srv)).id
        assert isinstance(runner.process(svc, iid), NeedsClarification)
        svc.inbox.clarify(iid, "short but real")  # any non-empty clarification counts once gating passes
        svc.inbox.clarify(iid, PASTE)
        assert isinstance(runner.process(svc, iid), Processed)
        src = svc.conn.execute("SELECT * FROM sources").fetchone()
        assert src["extractor"] == "user_clarification" and src["url"] is None and src["content_type"] == "note"
        assert src["title"].startswith("Quokkas")
        assert svc.conn.execute("SELECT count(*) FROM segments WHERE text LIKE '%Rottnest%'").fetchone()[0] == 1
        ev = svc.conn.execute("SELECT detail FROM processing_events WHERE inbox_id=? AND stage='user_text'", (iid,)).fetchone()
        assert ev and svc.inbox.get(iid)["canonical_url"] in ev["detail"]  # original URL kept as a note, not as source url


def test_clarify_cannot_fix_oversize_or_missing_backend(svc):
    svc.cfg.max_fetch_bytes = 50
    iid = svc.inbox.submit(adapter="t", file=b"x" * 200, filename="big.txt").id
    svc.inbox.clarify(iid, PASTE)
    out = runner.process(svc, iid)
    assert isinstance(out, NeedsClarification) and "max_fetch_bytes" in out.reason and "cannot fix" in out.reason
    svc.cfg.max_fetch_bytes = 50_000_000
    iid = svc.inbox.submit(adapter="t", file=b"\x89PNG\r\n\x1a\n" + b"x" * 20, filename="p.png").id
    svc.inbox.clarify(iid, PASTE)
    out = runner.process(svc, iid)
    assert isinstance(out, NeedsClarification) and "no OCR backend" in out.reason
    assert svc.conn.execute("SELECT count(*) FROM sources").fetchone()[0] == 0
