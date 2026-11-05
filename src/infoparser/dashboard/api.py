"""Dashboard logic as plain functions over Services (no HTTP here).

The server only routes and the UI only renders. Errors: ValueError -> 400, KeyError -> 404 (the
server maps them). Every URL sent to the UI is http(s) or None.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

from infoparser import digest as digest_mod
from infoparser import doctor
from infoparser.domain.display import inbox_label
from infoparser.inbox.ingest import handle
from infoparser.retrieval import ask as ask_mod
from infoparser.retrieval import search as search_mod
from infoparser.store import knowledge

MAX_TEXT = 200_000  # clarification / body edits
MAX_TITLE = 500
MAX_QUERY = 2000
_ID = re.compile(r"[0-9A-Za-z]{1,64}")
_INLINE = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}  # SVG/HTML are never rendered inline
_STATUSES = ("new", "pending", "processing", "processed", "failed", "needs_clarification")


def safe_url(u) -> str | None:
    """Return the URL only if it is http(s) with a host, else None."""
    if not isinstance(u, str):
        return None
    p = urlparse(u.strip())
    return u.strip() if p.scheme in ("http", "https") and p.netloc else None


def _str(body, key, *, required=True, cap=MAX_TEXT) -> str | None:
    v = body.get(key) if isinstance(body, dict) else None
    if v is None and not required:
        return None
    if not isinstance(v, str) or (required and not v.strip()):
        raise ValueError(f"{key} must be a non-empty string")
    if len(v) > cap:
        raise ValueError(f"{key} too long (max {cap} characters)")
    return v


def _id(v) -> str:
    if not isinstance(v, str) or not _ID.fullmatch(v):
        raise KeyError(v)
    return v


# ---- status / privacy
def state(s) -> dict:
    """Counts and flags for the status header."""
    counts = {k: 0 for k in _STATUSES}
    for r in s.conn.execute("SELECT status, count(*) n FROM inbox_items GROUP BY status"):
        counts[r["status"]] = r["n"]
    jobs = {
        r["state"]: r["n"]
        for r in s.conn.execute("SELECT state, count(*) n FROM jobs GROUP BY state")
    }
    return {
        "counts": counts,
        "jobs": jobs,
        "items": s.conn.execute(
            "SELECT count(*) FROM knowledge_items WHERE deleted_at IS NULL"
        ).fetchone()[0],
        "backends": s.registry.describe(),
        "allow_remote": s.cfg.allow_remote,
    }


def privacy(s) -> dict:
    """Backends, locality and egress summary for the settings view."""
    backends = [
        {"name": n, "locality": b.locality, "type": getattr(b, "type", None)}
        for n, b in s.registry.backends.items()
    ]
    return {
        "allow_remote": s.cfg.allow_remote,
        "backends": backends,
        "skipped": list(s.registry.skipped),
        "egress": doctor.egress_report(s.cfg),
        "note": "remote backends receive text only when allow_remote is true",
    }


# ---- inbox
def _what(r) -> str:
    return inbox_label(r, 120)


def _inbox_row(r) -> dict:
    return {
        "id": r["id"],
        "status": r["status"],
        "error": r["error"],
        "content_type": r["content_type"],
        "what": _what(r),
        "url": safe_url(r["payload_text"] if r["kind_hint"] == "url" else None),
        "submitted_at": r["submitted_at"],
        "updated_at": r["updated_at"],
        "attempts": r["attempts"],
        "source_id": r["source_id"],
        "user_context": r["user_context"],
    }


def inbox_list(s, status: str | None, limit: int = 200) -> list[dict]:
    """Inbox rows, optionally filtered by status."""
    if status and status not in _STATUSES:
        raise ValueError("unknown status")
    return [_inbox_row(r) for r in s.inbox.list(status or None, limit)]


def inbox_submit(s, body) -> dict:
    """Submit a URL, text or file body through the shared ingest path."""
    return handle(s.inbox, body, adapter="dashboard")


def inbox_get(s, iid: str) -> dict:
    """One inbox row with the knowledge items derived from it."""
    r = s.inbox.get(_id(iid))
    out = _inbox_row(r)
    out["items"] = (
        [
            {"id": k["id"], "title": k["title"], "kind": k["kind"], "provenance": k["provenance"]}
            for k in s.conn.execute(
                "SELECT id, title, kind, provenance FROM knowledge_items"
                " WHERE source_id=? AND deleted_at IS NULL ORDER BY created_at",
                (r["source_id"],),
            )
        ]
        if r["source_id"]
        else []
    )
    out["events"] = [
        dict(e)
        for e in s.conn.execute(
            "SELECT at, stage, status, detail FROM processing_events WHERE inbox_id=? ORDER BY id",
            (iid,),
        )
    ]
    out["has_blob"] = bool(r["blob_sha256"])
    out["blob_sha256"] = r["blob_sha256"]
    return out


def retry(s, iid: str) -> dict:
    """Re-queue a failed or clarification-pending item."""
    s.inbox.retry(_id(iid))
    return {"ok": True}


def clarify(s, iid: str, text) -> dict:
    """Attach the user clarification to an item and re-queue it."""
    t = _str({"text": text}, "text")
    s.inbox.clarify(_id(iid), t.strip())
    return {
        "ok": True,
        "note": "queued. Your text replaces the content only for a login/paywall, blocked page or "
        "empty/textless item; limits (file too large) and missing backends (OCR, "
        "transcriber) stay as they are, because pasted text cannot fix them (you will see "
        "'cannot fix this').",
    }


# ---- items
def _live_item(s, item_id):
    it = knowledge.get_item(s.conn, _id(item_id))
    if it is None or it["deleted_at"]:
        raise KeyError(item_id)
    return it


def item_detail(s, item_id: str) -> dict:
    """A knowledge item with its source, provenance, links and related items."""
    it = _live_item(s, item_id)
    c = s.conn
    src = (
        c.execute("SELECT * FROM sources WHERE id=?", (it["source_id"],)).fetchone()
        if it["source_id"]
        else None
    )
    cites = []
    for sid in it["segment_refs"]:
        g = c.execute("SELECT locator, text FROM segments WHERE id=?", (sid,)).fetchone()
        if g:
            cites.append({"segment_id": sid, "locator": g["locator"], "text": g["text"][:600]})
    rel = []
    for r in c.execute(
        "SELECT r.type, r.score, k.id, k.title FROM relations r JOIN knowledge_items k"
        " ON k.id = CASE WHEN r.item_a=? THEN r.item_b ELSE r.item_a END"
        " WHERE (r.item_a=? OR r.item_b=?) AND k.deleted_at IS NULL ORDER BY r.score DESC LIMIT 20",
        (item_id, item_id, item_id),
    ):
        rel.append({"id": r["id"], "title": r["title"], "type": r["type"], "score": r["score"]})
    inbox = (
        [
            {"inbox_id": r["inbox_id"], "url": safe_url(r["url"]), "added_at": r["added_at"]}
            for r in c.execute(
                "SELECT inbox_id, url, added_at FROM provenance_log WHERE source_id=? ORDER BY id",
                (it["source_id"],),
            )
        ]
        if it["source_id"]
        else []
    )
    data = it["data"]
    return {
        "id": it["id"],
        "kind": it["kind"],
        "title": it["title"],
        "body": it["body"],
        "provenance": it["provenance"],
        "confidence": it["confidence"],
        "user_edited": bool(it["user_edited"]),
        "flagged": bool(it["flagged"]),
        "version": it["version"],
        "extracted_by": it["extracted_by"],
        "created_at": it["created_at"],
        "updated_at": it["updated_at"],
        "evidence": data.get("evidence"),
        "source": {
            "id": src["id"],
            "title": src["title"],
            "url": safe_url(src["url"]),
            "platform": src["platform"],
            "content_type": src["content_type"],
            "blob_sha256": src["blob_sha256"],
        }
        if src
        else None,
        "citations": cites,
        "related": rel,
        "inbox": inbox,
        "topics": [
            r[0]
            for r in c.execute(
                "SELECT t.name FROM item_topics i JOIN topics t ON t.id=i.topic_id"
                " WHERE i.item_id=? ORDER BY t.name",
                (item_id,),
            )
        ],
        "entities": [
            r[0]
            for r in c.execute(
                "SELECT e.name FROM item_entities i JOIN entities e ON e.id=i.entity_id"
                " WHERE i.item_id=? ORDER BY e.name",
                (item_id,),
            )
        ],
    }


def item_update(s, item_id: str, body) -> dict:
    """Edit an item; user edits are preserved on reprocess."""
    if not isinstance(body, dict) or not body or set(body) - {"title", "body"}:
        raise ValueError("body must be an object with title and/or body")
    fields = {}
    if "title" in body:
        fields["title"] = _str(body, "title", cap=MAX_TITLE)
    if "body" in body:
        fields["body"] = _str(body, "body")
    _live_item(s, item_id)
    knowledge.update_item(s.conn, item_id, **fields)
    return item_detail(s, item_id)


def item_delete(s, item_id: str) -> dict:
    """Soft-delete an item."""
    _live_item(s, item_id)
    knowledge.delete_item(s.conn, item_id)
    return {"ok": True}


def item_reprocess(s, item_id: str) -> dict:
    """Re-run the pipeline for the item source."""
    it = _live_item(s, item_id)
    row = (
        s.conn.execute(
            "SELECT id FROM inbox_items WHERE source_id=? ORDER BY submitted_at LIMIT 1",
            (it["source_id"],),
        ).fetchone()
        if it["source_id"]
        else None
    )
    if row is None:
        raise KeyError("no inbox item to reprocess")
    s.inbox.retry(row["id"])
    return {"ok": True, "inbox_id": row["id"]}


# ---- search / ask
def _hit(h) -> dict:
    return {
        "item_id": h.item_id,
        "segment_id": h.segment_id,
        "source_id": h.source_id,
        "title": h.title,
        "snippet": h.snippet,
        "source_url": safe_url(h.source_url),
        "locator": h.locator,
        "provenance": h.provenance,
        "kind": h.kind,
        "score": h.score,
    }


def search(s, q: str, filters: dict, limit: int = 20) -> dict:
    """Hybrid search with filters; reports the retrieval mode."""
    if not isinstance(q, str) or len(q) > MAX_QUERY:
        raise ValueError("q must be a string")
    res = search_mod.search_ex(s, q, limit=limit, filters={k: v for k, v in filters.items() if v})
    return {
        "mode": res.mode,
        "warnings": res.warnings,
        "egress": res.egress,
        "hits": [_hit(h) for h in res.hits],
    }


def ask(s, q) -> dict:
    """Answer a question from cited excerpts."""
    q = _str({"q": q}, "q", cap=MAX_QUERY)
    d = ask_mod.ask(s, q.strip()).to_dict()
    for e in d["retrieved"]:
        e["url"] = safe_url(e["url"])
        e["deep_link"] = safe_url(e["deep_link"])
    d["deep_links"] = [u for u in map(safe_url, d["deep_links"]) if u]
    return d


# ---- library views
def topics(s) -> list[dict]:
    """Topics with live item counts."""
    return [
        dict(r)
        for r in s.conn.execute(
            "SELECT t.name, count(*) n FROM topics t JOIN item_topics i ON i.topic_id=t.id"
            " JOIN knowledge_items k ON k.id=i.item_id AND k.deleted_at IS NULL"
            " GROUP BY t.id ORDER BY n DESC, t.name"
        )
    ]


def duplicates(s) -> list[dict]:
    """Near-duplicate item pairs."""
    out = []
    for r in s.conn.execute(
        "SELECT r.score, a.id aid, a.title atitle, b.id bid, b.title btitle FROM relations r"
        " JOIN knowledge_items a ON a.id=r.item_a AND a.deleted_at IS NULL"
        " JOIN knowledge_items b ON b.id=r.item_b AND b.deleted_at IS NULL"
        " WHERE r.type='duplicate' ORDER BY r.score DESC LIMIT 200"
    ):
        out.append(
            {
                "score": r["score"],
                "a": {"id": r["aid"], "title": r["atitle"]},
                "b": {"id": r["bid"], "title": r["btitle"]},
            }
        )
    return out


def digest(s, days: int = 7) -> dict:
    """Dry run of the real digest module: writes no file, so viewing cannot use up the interval."""
    d = digest_mod.data(s, since_days=days)
    return {
        **d,
        "days": days,
        "total": d["new"]["total"],
        "items": d["new"]["items"],
        "markdown": digest_mod.render(d),
    }


# ---- blobs
def blob(s, sha: str) -> tuple[Path, str, bool]:
    """Return (path, content-type, inline). Only blobs the DB knows; SHA is 64 lowercase hex."""
    path = s.blobs.path(sha)  # ValueError for anything but 64 hex chars
    row = s.conn.execute(
        "SELECT original_filename FROM inbox_items WHERE blob_sha256=? LIMIT 1", (sha,)
    ).fetchone()
    if (
        row is None
        and not s.conn.execute(
            "SELECT 1 FROM sources WHERE blob_sha256=? LIMIT 1", (sha,)
        ).fetchone()
    ):
        raise KeyError(sha)
    if not path.is_file():
        raise KeyError(sha)
    ext = Path((row["original_filename"] if row else "") or "").suffix.lower()
    ctype = _INLINE.get(ext)
    if ctype:
        head = path.read_bytes()[:12]
        sniff = {
            ".png": head.startswith(b"\x89PNG"),
            ".jpg": head.startswith(b"\xff\xd8"),
            ".jpeg": head.startswith(b"\xff\xd8"),
            ".gif": head.startswith(b"GIF8"),
            ".webp": head[:4] == b"RIFF" and head[8:12] == b"WEBP",
        }[ext]
        if not sniff:  # extension lies about the content: never serve inline
            ctype = None
    return path, ctype or "application/octet-stream", ctype is not None
