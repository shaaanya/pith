"""Per-note state: done, snooze, hidden-from-resurfacing, and last viewed.

Keyed by owner = the note's source id (its own id when it has no source), because reprocess replaces
the note row and what the user did with the note must survive that."""
from datetime import datetime

from pith.ids import utcnow

_UNSET = object()


def owner_of(conn, item_id) -> str:
    r = conn.execute("SELECT id, source_id FROM knowledge_items WHERE id=?", (item_id,)).fetchone()
    if r is None:
        raise KeyError(item_id)
    return r["source_id"] or r["id"]


def get(conn, owner) -> dict:
    r = conn.execute("SELECT * FROM note_state WHERE owner=?", (owner,)).fetchone()
    return {"done_at": r["done_at"] if r else None, "snooze_until": r["snooze_until"] if r else None,
            "hidden": bool(r["hidden"]) if r else False}


def _iso(v) -> str:
    if not isinstance(v, str):
        raise ValueError("snooze_until must be an ISO time or null")
    try:
        datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError as e:
        raise ValueError("snooze_until must be an ISO time or null") from e
    return v


def set_state(conn, owner, *, done=_UNSET, snooze_until=_UNSET, hidden=_UNSET) -> dict:
    """Change only the fields given: done (bool), snooze_until (ISO string or None), hidden (bool)."""
    cur, now = get(conn, owner), utcnow()
    if done is not _UNSET:
        cur["done_at"] = now if done else None
    if snooze_until is not _UNSET:
        cur["snooze_until"] = None if snooze_until is None else _iso(snooze_until)
    if hidden is not _UNSET:
        cur["hidden"] = bool(hidden)
    conn.execute(
        "INSERT INTO note_state(owner,done_at,snooze_until,hidden,updated_at) VALUES (?,?,?,?,?)"
        " ON CONFLICT(owner) DO UPDATE SET done_at=excluded.done_at,"
        " snooze_until=excluded.snooze_until, hidden=excluded.hidden, updated_at=excluded.updated_at",
        (owner, cur["done_at"], cur["snooze_until"], int(cur["hidden"]), now))
    return cur


def mark_viewed(conn, item_id) -> bool:
    """Record that the note was opened (sets last_viewed_at). False for an unknown id."""
    return conn.execute("UPDATE knowledge_items SET last_viewed_at=? WHERE id=?",
                        (utcnow(), item_id)).rowcount > 0
