"""detect -> extract -> chunk -> distill -> save source/segments/items. Idempotent per inbox_id."""
import contextlib
import hashlib
import importlib
import json
import sqlite3
import time
from urllib.parse import urlparse

from pith.domain.models import SegmentIn
from pith.ids import utcnow
from pith.jobs import require_lease
from pith.pipeline.chunk import chunk_text, chunk_timed
from pith.pipeline.detect import detect
from pith.pipeline import dedupe, entities, note, place, provenance
from pith.providers import egress
from pith.pipeline.distill import distill
from pith.pipeline.schemas import profile_for
from pith.pipeline.extractors.base import (
    EXTRACTORS,
    Extracted,
    ExtractCtx,
    NeedsClarificationError,
)
from pith.retrieval import index
from pith.store import entries as entry_store, knowledge, shelves
from pith.store.db import transaction
from pith.worker import Failed, NeedsClarification, Processed

importlib.import_module("pith.pipeline.extractors")  # registers the extractors

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
    "from file.txt" or "Telegram message ..." is provenance, never a reason; notes added later
    (`user_note`) always are."""
    ctx = (row["user_context"] or "").strip()
    ctx = ctx if row["adapter"] not in _SYSTEM_ADAPTERS else ""
    return "\n\n".join(x for x in (ctx, ((row["user_note"] if "user_note" in row.keys() else "") or "").strip()) if x) or None


def _limits(ex, ct):
    """What this extraction could not read, stated in the note instead of hidden."""
    out = []
    if ex.metadata.get("frames_error"):
        out.append("Video frames could not be analysed")
    elif ct == "video" and not any("[visual]" in t.text for t in ex.timed or []):
        out.append("Only speech and the caption were read; on-screen content was not analysed")
    return out


@contextlib.contextmanager
def audited(s, inbox_id: str):
    """Audit remote model calls against this inbox item while the block runs."""
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
        yield
    finally:
        egress.sink.reset(tok)


def process(services, inbox_id: str):
    """Run one inbox item through the pipeline, auditing remote calls against it."""
    with audited(services, inbox_id):
        return _process(services, inbox_id)


def sync_entries(s, inbox_id: str, item_ids) -> None:
    """Each `resource` unit of a note (a film, a song, a tool it names) becomes an entry of its own
    that can be ticked off. Never raises: a failure is logged."""
    t0 = time.monotonic()
    try:
        q = ",".join("?" * len(item_ids))
        notes = s.conn.execute(
            f"SELECT id, source_id, data_json FROM knowledge_items WHERE id IN ({q})"
            " AND kind='note' AND deleted_at IS NULL", list(item_ids)).fetchall()
        n = 0
        with transaction(s.conn):
            require_lease(s.conn)
            for r in notes:
                units = json.loads(r["data_json"] or "{}").get("units", [])
                texts = [u["text"] for u in units if u.get("type") == "resource" and u.get("text")]
                n += len(entry_store.sync(s.conn, r["source_id"] or r["id"], r["id"], texts))
        if n:
            _stage(s.conn, inbox_id, "entries", t0, f"{n} entries")
    except Exception as e:  # pylint: disable=broad-exception-caught  # entries are optional
        try:
            _stage(s.conn, inbox_id, "entries", t0, f"{type(e).__name__}: {e}", level="error")
        except Exception:  # pylint: disable=broad-exception-caught  # item already saved
            pass


def backfill(s) -> int:
    """Notes saved before placement existed (placement_by NULL) get a rule-based shelf and their
    entries. No model, nothing leaves the machine; idempotent. Returns how many notes were placed."""
    rows = s.conn.execute(
        "SELECT k.id, k.source_id, k.body, k.data_json, src.url FROM knowledge_items k"
        " LEFT JOIN sources src ON src.id=k.source_id"
        " WHERE k.kind='note' AND k.deleted_at IS NULL AND k.placement_by IS NULL").fetchall()
    for r in rows:
        ib = s.conn.execute("SELECT * FROM inbox_items WHERE source_id=? ORDER BY submitted_at LIMIT 1",
                            (r["source_id"],)).fetchone() if r["source_id"] else None
        host = urlparse(r["url"]).netloc if r["url"] else None
        shelf, by, why = place.rules(intent_of(ib) if ib else None, host, bool((r["body"] or "").strip()))
        units = json.loads(r["data_json"] or "{}").get("units", [])
        with transaction(s.conn):
            shelves.set_placement(s.conn, r["id"], shelf, by, why)
            entry_store.sync(s.conn, r["source_id"] or r["id"], r["id"],
                             [u["text"] for u in units if u.get("type") == "resource" and u.get("text")])
    return len(rows)


def place_items(s, inbox_id: str, item_ids) -> int:
    """Put the notes among `item_ids` on a shelf (model, then rules). Never raises: a failure is
    logged and the note keeps its rule/default placement. A shelf the user chose is left alone.
    Returns how many notes were placed."""
    t0 = time.monotonic()
    try:
        q = ",".join("?" * len(item_ids))
        rows = s.conn.execute(
            "SELECT k.id, k.kind, k.title, k.body, k.placement_by, k.extracted_by, src.url"
            " FROM knowledge_items k"
            f" LEFT JOIN sources src ON src.id=k.source_id WHERE k.id IN ({q})"
            " AND k.kind IN ('note','summary') AND k.deleted_at IS NULL", list(item_ids)).fetchall()
        if any(r["kind"] == "note" for r in rows):
            rows = [r for r in rows if r["kind"] == "note"]
        rows = [r for r in rows if r["placement_by"] != "user"]
        if not rows:
            return 0
        intent = intent_of(s.inbox.get(inbox_id))
        backend = next((b for b in s.registry.chain("distill")
                        if getattr(b, "type", "") != "heuristic"), None)
        shelf_list = shelves.list_shelves(s.conn)
        local = getattr(backend, "locality", "local") == "local"
        decided = []  # model calls happen here, outside any write transaction
        for r in rows:
            # a short note was kept verbatim so nothing left the machine: keep it that way
            b = None if r["extracted_by"] == "verbatim" and not local else backend
            host = urlparse(r["url"]).netloc if r["url"] else None
            decided.append((r["id"], *place.decide(b, r["title"], r["body"], intent, host,
                                                   shelf_list)))
        with transaction(s.conn):
            require_lease(s.conn)
            for item_id, shelf, by, why, model in decided:
                shelves.set_placement(s.conn, item_id, shelf, by, why, model)
        _stage(s.conn, inbox_id, "place", t0,
               f"{len(rows)} on {decided[-1][1]} by {decided[-1][2]}", model=decided[-1][4])
        return len(rows)
    except Exception as e:  # pylint: disable=broad-exception-caught  # placement is optional
        try:
            _stage(s.conn, inbox_id, "place", t0, f"{type(e).__name__}: {e}", level="error")
        except Exception:  # pylint: disable=broad-exception-caught  # item already saved
            pass
        return 0


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
        title = note.real_title(ex.title)
        made = note.build(s.registry, segs, title=title, intent=intent_of(row),
                          limits=_limits(ex, ct), kind=ct)
        cands, by = made or distill(s.registry, segs, profile=profile_of(ct, row["user_context"]),
                                    title=title, user_context=intent_of(row))
        _stage(s.conn, inbox_id, "distill", t0, f"{len(cands)} items", model=by)
        t0 = time.monotonic()
        sid, item_ids = _save(s, row, ex, ct, (segs, cands, by))
        _stage(s.conn, inbox_id, "save", t0, sid)
        place_items(s, inbox_id, item_ids)
        sync_entries(s, inbox_id, item_ids)
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
