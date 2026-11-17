"""detect -> extract -> chunk -> distill -> save source/segments/items. Idempotent per inbox_id."""
import hashlib
import importlib
import json
import sqlite3
import time

from infoparser.domain.models import SegmentIn
from infoparser.ids import utcnow
from infoparser.jobs import require_lease
from infoparser.pipeline.chunk import chunk_text, chunk_timed
from infoparser.pipeline.detect import detect
from infoparser.pipeline import dedupe, entities, note, provenance
from infoparser.providers import egress
from infoparser.pipeline.distill import distill
from infoparser.pipeline.schemas import profile_for
from infoparser.pipeline.extractors.base import (
    EXTRACTORS,
    Extracted,
    ExtractCtx,
    NeedsClarificationError,
)
from infoparser.retrieval import index
from infoparser.store import knowledge
from infoparser.store.db import transaction
from infoparser.worker import Failed, NeedsClarification, Processed

importlib.import_module("infoparser.pipeline.extractors")  # registers the extractors

def _from_clarification(conn, row, err):
    """The user answered a needs_clarification.

    Their LATEST explicit clarification becomes the content, but only for problems pasted text
    can solve (err.pasteable). Anything else keeps its original reason.
    """
    last = conn.execute("SELECT detail FROM processing_events"
                        " WHERE inbox_id=? AND stage='clarified'"
                        " ORDER BY id DESC LIMIT 1", (row["id"],)).fetchone()
    text = (last["detail"] if last else "").strip()
    if not text:
        raise err
    if not err.pasteable:
        raise NeedsClarificationError(f"{err.reason} (pasted text cannot fix this)") from None
    _stage(conn, row["id"], "user_text", time.monotonic(),
           f"text supplied by the user; original url: {row['canonical_url'] or '-'}")
    return Extracted(text.splitlines()[0][:80], None, None, "note", text,
                     original_sha=row["blob_sha256"], extractor="user_clarification")


# pylint: disable-next=too-many-arguments,too-many-positional-arguments  # log-row fields
def _stage(conn, iid, stage, t0, detail="", model=None, level="info"):
    conn.execute(
        "INSERT INTO processing_events(inbox_id, at, stage, status, detail, duration_ms, model)"
        " VALUES (?,?,?,?,?,?,?)",
        (iid, utcnow(), stage, level, detail,
         int((time.monotonic() - t0) * 1000), model))


def profile_of(ct, hints):
    """Distillation profile for a content type (code/pdf default to their own profiles)."""
    p = profile_for(ct, hints)
    return {"code": "programming", "pdf": "paper"}.get(ct, p) if p == "generic" else p


_SYSTEM_ADAPTERS = {"fs", "telegram_export"}  # their user_context is machine-written provenance


def intent_of(row):
    """The user's own reason for saving, or None (unknown). Adapter-written context such as
    "from file.txt" or "Telegram message ..." is provenance, never a reason."""
    ctx = (row["user_context"] or "").strip()
    return ctx if ctx and row["adapter"] not in _SYSTEM_ADAPTERS else None


def _limits(ex, ct):
    """What this extraction could not read, stated in the note instead of hidden."""
    out = []
    if ex.metadata.get("frames_error"):
        out.append("Video frames could not be analysed")
    elif ct == "video" and not any("[visual]" in t.text for t in ex.timed or []):
        out.append("Only speech and the caption were read; on-screen content was not analysed")
    return out


def process(services, inbox_id: str):
    """Run one inbox item through the pipeline, auditing remote calls against it."""
    s = services

    def sink(backend, nbytes):
        """Audit row per remote call, attributed to THIS inbox item (incl. embed_pending).

        Fail-open: an audit write failure must not abort the call (one stderr warning).
        """
        try:
            s.conn.execute(
                "INSERT INTO processing_events"
                "(inbox_id, at, stage, status, detail, backend, egress)"
                " VALUES (?,?,?,?,?,?,1)",
                (inbox_id, utcnow(), "egress", "info", json.dumps({"bytes_sent": nbytes}), backend))
        except sqlite3.Error as e:
            egress.warn_once(f"egress audit write failed: {e}")
    tok = egress.sink.set(sink)
    try:
        return _process(services, inbox_id)
    finally:
        egress.sink.reset(tok)


def _text_sha(ex):
    return hashlib.sha256(ex.text.encode()).hexdigest()


def _share_twin(s, row, ex, ct, t0):
    """Same text already ingested (e.g. via another URL): share that source. True when shared."""
    inbox_id = row["id"]
    twin = s.conn.execute("SELECT id FROM sources WHERE text_sha256=? ORDER BY fetched_at LIMIT 1",
                          (_text_sha(ex),)).fetchone()
    if not twin:
        return False
    orig = s.conn.execute("SELECT inbox_id FROM provenance_log WHERE source_id=? AND inbox_id<>?"
                          " ORDER BY id LIMIT 1", (twin["id"], inbox_id)).fetchone()
    with transaction(s.conn):
        require_lease(s.conn)
        s.conn.execute("INSERT INTO provenance_log(source_id, inbox_id, url, added_at)"
                       " VALUES (?,?,?,?)", (twin["id"], inbox_id, ex.url, utcnow()))
        s.conn.execute("UPDATE inbox_items SET source_id=?, content_type=? WHERE id=?",
                       (twin["id"], ct, inbox_id))
    first = orig["inbox_id"] if orig else "?"
    _stage(s.conn, inbox_id, "duplicate", t0,
           f"same text as source {twin['id']} (first submitted as inbox {first}); no new source")
    return True


def _pieces(ex):
    """Chunk the extracted content, keeping timestamp/page/post-level locators."""
    if ex.timed:
        out = chunk_timed(ex.timed)
    elif ex.sections:
        out = [(t, loc) for loc, body in ex.sections for t, _ in chunk_text(body)]
    else:
        out = chunk_text(ex.text)
    desc = (ex.metadata.get("description") or "").strip()  # author's caption: often the densest part
    return [(desc, "description"), *out] if desc else out


def _save(s, row, ex, ct, distilled):
    """One transaction: upsert the source (reprocess refreshes its url), segments and items."""
    inbox_id, text_sha = row["id"], _text_sha(ex)
    segs, cands, by = distilled
    with transaction(s.conn):
        require_lease(s.conn)
        sid = row["source_id"]
        now = s.conn.execute("SELECT source_id FROM inbox_items WHERE id=?", (inbox_id,)).fetchone()
        if now is None or now["source_id"] != sid:  # another worker saved since we started
            raise RuntimeError("lost the lease: the item was saved by another worker; "
                               "result discarded")
        if sid:
            s.conn.execute(
                "UPDATE sources SET title=?, author=?, content_type=?, text_sha256=?, extractor=?,"
                " fetched_at=?, url=COALESCE(?, url) WHERE id=?",
                (ex.title, ex.author, ct, text_sha, ex.extractor or ct, utcnow(), ex.url, sid))
        else:
            sid = knowledge.save_source(
                s.conn, url=ex.url, title=ex.title, author=ex.author, platform=row["platform"],
                content_type=ct, blob_sha256=ex.original_sha or row["blob_sha256"],
                text_sha256=text_sha, extractor=ex.extractor or ct)
            s.conn.execute("INSERT INTO provenance_log(source_id, inbox_id, url, added_at)"
                           " VALUES (?,?,?,?)", (sid, inbox_id, ex.url, utcnow()))
        seg_ids = knowledge.save_segments(s.conn, sid, segs)
        item_ids = knowledge.save_items(s.conn, sid, cands, by, seg_ids)
        provenance.recheck_edited(s.conn, sid)
        s.conn.execute("UPDATE inbox_items SET source_id=?, content_type=? WHERE id=?",
                       (sid, ct, inbox_id))
    return sid, item_ids


def enrich(s, inbox_id, item_ids, cands):
    """Best-effort enrichment: a failure is logged, never fails the item."""
    steps = (("entities", lambda: entities.apply(s.conn, item_ids, cands) or len(item_ids)),
             ("embed", lambda: index.embed_pending(s)),
             ("dedupe", lambda: dedupe.find_near_duplicates(s.conn, item_ids, s)))
    for stage, fn in steps:
        t0 = time.monotonic()
        try:
            r = fn()
            _stage(s.conn, inbox_id, stage, t0, str(r if isinstance(r, int) else len(r)))
        except Exception as e:  # pylint: disable=broad-exception-caught  # enrichment is optional
            try:
                _stage(s.conn, inbox_id, stage, t0, f"{type(e).__name__}: {e}", level="error")
            except Exception:  # pylint: disable=broad-exception-caught  # item already saved
                pass


def _extract(s, row, ct):
    """Run the extractor; a clarification the user already answered becomes the content."""
    try:
        ex = EXTRACTORS[ct](ExtractCtx(row, s.blobs, s.registry, s.cfg))
    except NeedsClarificationError as e:
        ex = _from_clarification(s.conn, row, e)
        ct = ex.content_type  # the stored source is the user's note, not the unreadable original
    return ex, ct


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
        ex, ct = _extract(s, row, ct)
        _stage(s.conn, inbox_id, "extract", t0, f"{len(ex.text)} chars")
        if not row["source_id"] and _share_twin(s, row, ex, ct, t0):
            return Processed()
        t0 = time.monotonic()
        segs = [SegmentIn(i, t, loc) for i, (t, loc) in enumerate(_pieces(ex))]
        _stage(s.conn, inbox_id, "chunk", t0, f"{len(segs)} segments")
        t0 = time.monotonic()
        made = note.build(s.registry, segs, title=ex.title or "", intent=intent_of(row),
                          limits=_limits(ex, ct), kind=ct)
        cands, by = made or distill(s.registry, segs, profile=profile_of(ct, row["user_context"]),
                                    title=ex.title or "", user_context=intent_of(row))
        _stage(s.conn, inbox_id, "distill", t0, f"{len(cands)} items", model=by)
        t0 = time.monotonic()
        sid, item_ids = _save(s, row, ex, ct, (segs, cands, by))
        _stage(s.conn, inbox_id, "save", t0, sid)
        enrich(s, inbox_id, item_ids, cands)
        return Processed()
    except NeedsClarificationError as e:
        return NeedsClarification(e.reason)
    except Exception as e:  # pylint: disable=broad-exception-caught  # original kept; worker retries
        msg = f"{type(e).__name__}: {e}"
        try:
            _stage(s.conn, inbox_id, "error", t0, msg, level="error")
        except Exception:  # pylint: disable=broad-exception-caught  # keep the original
            pass
        return Failed(msg)
