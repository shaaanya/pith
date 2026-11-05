"""detect -> extract -> chunk -> save source/segments -> distill -> save items. Idempotent per inbox_id."""
import hashlib
import json
import time

from infoparser.domain.models import SegmentIn
from infoparser.ids import utcnow
from infoparser.pipeline import extractors  # noqa: F401  (registers extractors)
from infoparser.pipeline.chunk import chunk_text, chunk_timed
from infoparser.pipeline.detect import detect
from infoparser.pipeline import dedupe, entities
from infoparser.providers import egress
from infoparser.pipeline.distill import distill
from infoparser.pipeline.schemas import profile_for
from infoparser.pipeline.extractors.base import EXTRACTORS, Extracted, ExtractCtx, NeedsClarificationError
from infoparser.retrieval import index
from infoparser.store import knowledge
from infoparser.store.db import transaction
from infoparser.worker import Failed, NeedsClarification, Processed

def _from_clarification(conn, row, err):
    """The user answered a needs_clarification. Their LATEST explicit clarification becomes the content, but only
    for problems pasted text can solve (err.pasteable). Anything else keeps its original reason."""
    last = conn.execute("SELECT detail FROM processing_events WHERE inbox_id=? AND stage='clarified'"
                        " ORDER BY id DESC LIMIT 1", (row["id"],)).fetchone()
    text = (last["detail"] if last else "").strip()
    if not text:
        raise err
    if not err.pasteable:
        raise NeedsClarificationError(f"{err.reason} (pasted text cannot fix this)") from None
    _stage(conn, row["id"], "user_text", time.monotonic(),
           f"text supplied by the user; original url: {row['canonical_url'] or '-'}")
    return Extracted(text.splitlines()[0][:80], None, None, "note", text, original_sha=row["blob_sha256"],
                     extractor="user_clarification")


def _stage(conn, iid, stage, t0, detail="", model=None, level="info"):
    conn.execute(
        "INSERT INTO processing_events(inbox_id, at, stage, status, detail, duration_ms, model)"
        " VALUES (?,?,?,?,?,?,?)",
        (iid, utcnow(), stage, level, detail,
         int((time.monotonic() - t0) * 1000), model))


def _profile(ct, hints):
    p = profile_for(ct, hints)
    return {"code": "programming", "pdf": "paper"}.get(ct, p) if p == "generic" else p


def process(services, inbox_id: str):
    s = services

    def sink(backend, nbytes):  # every call to a remote backend leaves an audit row for this inbox item
        s.conn.execute(
            "INSERT INTO processing_events(inbox_id, at, stage, status, detail, backend, egress)"
            " VALUES (?,?,?,?,?,?,1)", (inbox_id, utcnow(), "egress", "info", json.dumps({"bytes_sent": nbytes}), backend))
    tok = egress.sink.set(sink)
    try:
        return _process(services, inbox_id)
    finally:
        egress.sink.reset(tok)


def _process(services, inbox_id: str):
    s = services
    t0 = time.monotonic()
    try:
        row = s.inbox.get(inbox_id)
        ct = detect(row, s.blobs)
        _stage(s.conn, inbox_id, "detect", t0, ct)
        if ct not in EXTRACTORS:
            raise NeedsClarificationError(f"no extractor available for content type '{ct}'")
        t0 = time.monotonic()
        try:
            ex = EXTRACTORS[ct](ExtractCtx(row, s.blobs, s.registry, s.cfg))
        except NeedsClarificationError as e:
            ex = _from_clarification(s.conn, row, e)
            ct = ex.content_type  # the stored source is the user's note, not the unreadable original
        _stage(s.conn, inbox_id, "extract", t0, f"{len(ex.text)} chars")
        text_sha = hashlib.sha256(ex.text.encode()).hexdigest()
        if not row["source_id"]:  # same text already ingested (e.g. via another URL): share the source
            twin = s.conn.execute("SELECT id FROM sources WHERE text_sha256=? ORDER BY fetched_at LIMIT 1",
                                  (text_sha,)).fetchone()
            if twin:
                orig = s.conn.execute("SELECT inbox_id FROM provenance_log WHERE source_id=? AND inbox_id<>?"
                                      " ORDER BY id LIMIT 1", (twin["id"], inbox_id)).fetchone()
                with transaction(s.conn):
                    s.conn.execute("INSERT INTO provenance_log(source_id, inbox_id, url, added_at) VALUES (?,?,?,?)",
                                   (twin["id"], inbox_id, ex.url, utcnow()))
                    s.conn.execute("UPDATE inbox_items SET source_id=?, content_type=? WHERE id=?",
                                   (twin["id"], ct, inbox_id))
                _stage(s.conn, inbox_id, "duplicate", t0, f"same text as source {twin['id']} (first submitted as inbox "
                       f"{orig['inbox_id'] if orig else '?'}); no new source")
                return Processed()
        t0 = time.monotonic()
        if ex.timed:
            pieces = chunk_timed(ex.timed)
        elif ex.sections:  # page/slide/post-level locators survive chunking
            pieces = [(t, loc) for loc, body in ex.sections for t, _ in chunk_text(body)]
        else:
            pieces = chunk_text(ex.text)
        segs = [SegmentIn(i, t, loc) for i, (t, loc) in enumerate(pieces)]
        _stage(s.conn, inbox_id, "chunk", t0, f"{len(segs)} segments")
        t0 = time.monotonic()
        cands, by = distill(s.registry, segs, profile=_profile(ct, row["user_context"]), title=ex.title or "",
                            user_context=row["user_context"])
        _stage(s.conn, inbox_id, "distill", t0, f"{len(cands)} items", model=by)
        t0 = time.monotonic()
        with transaction(s.conn):
            sid = row["source_id"]
            if sid:
                s.conn.execute("UPDATE sources SET title=?, author=?, content_type=?, text_sha256=?, extractor=?,"
                               " fetched_at=? WHERE id=?", (ex.title, ex.author, ct, text_sha, ex.extractor or ct, utcnow(), sid))
            else:
                sid = knowledge.save_source(
                    s.conn, url=ex.url, title=ex.title, author=ex.author, platform=row["platform"],
                    content_type=ct, blob_sha256=ex.original_sha or row["blob_sha256"],
                    text_sha256=text_sha, extractor=ex.extractor or ct)
                s.conn.execute("INSERT INTO provenance_log(source_id, inbox_id, url, added_at) VALUES (?,?,?,?)",
                               (sid, inbox_id, ex.url, utcnow()))
            seg_ids = knowledge.save_segments(s.conn, sid, segs)
            item_ids = knowledge.save_items(s.conn, sid, cands, by, seg_ids)
            s.conn.execute("UPDATE inbox_items SET source_id=?, content_type=? WHERE id=?", (sid, ct, inbox_id))
        _stage(s.conn, inbox_id, "save", t0, sid)
        for stage, fn in (("entities", lambda: entities.apply(s.conn, item_ids, cands) or len(item_ids)),
                          ("embed", lambda: index.embed_pending(s)),
                          ("dedupe", lambda: dedupe.find_near_duplicates(s.conn, item_ids, s))):
            t0 = time.monotonic()  # best-effort enrichment: a failure is logged, never fails the item
            try:
                r = fn()
                _stage(s.conn, inbox_id, stage, t0, str(r if isinstance(r, int) else len(r)))
            except Exception as e:  # noqa: BLE001
                try:
                    _stage(s.conn, inbox_id, stage, t0, f"{type(e).__name__}: {e}", level="error")
                except Exception:  # noqa: BLE001 - the item is already saved; never fail it over a log write
                    pass
        return Processed()
    except NeedsClarificationError as e:
        return NeedsClarification(e.reason)
    except Exception as e:  # noqa: BLE001 - original blob is untouched; record and let the worker retry/fail
        msg = f"{type(e).__name__}: {e}"
        try:
            _stage(s.conn, inbox_id, "error", t0, msg, level="error")
        except Exception:  # noqa: BLE001 - never mask the original error
            pass
        return Failed(msg)
