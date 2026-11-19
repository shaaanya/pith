"""Entries: the individual things a note names (five films, three songs), each tickable on its own.

Keyed by the note's owner (source id) so reprocess keeps done marks: a new extraction matches old
entries by normalised text."""
import difflib
import re

from pith.ids import new_id, utcnow


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def _view(r) -> dict:
    return {"id": r["id"], "text": r["text"], "done_at": r["done_at"], "position": r["position"]}


def for_item(conn, item_id) -> list[dict]:
    return [_view(r) for r in conn.execute(
        "SELECT * FROM entries WHERE item_id=? ORDER BY position", (item_id,))]


def sync(conn, owner, item_id, texts) -> list[dict]:
    """Make the entries of this note `texts` (deduped, in order). An existing entry keeps its id and
    done mark when its normalised text matches, or, for a done one, when a reworded line is nearly the
    same (the model rewords on reprocess). Vanished entries are dropped, except done ones: a tick is
    the user's own record and is never deleted by a reprocess."""
    seen, want = set(), []
    for t in texts:
        t = re.sub(r"\s+", " ", str(t)).strip()
        if t and _norm(t) not in seen:
            seen.add(_norm(t))
            want.append(t)
    old = {r["norm"]: r for r in conn.execute("SELECT * FROM entries WHERE owner=?", (owner,))}
    match = {t: old[_norm(t)] for t in want if _norm(t) in old}
    free = [t for t in want if t not in match]
    for r in old.values():  # done entries whose text changed: pair with the closest unmatched line
        if r["done_at"] and r["norm"] not in seen and free:
            best = max(free, key=lambda t: difflib.SequenceMatcher(None, r["norm"], _norm(t)).ratio())
            if difflib.SequenceMatcher(None, r["norm"], _norm(best)).ratio() >= 0.85:
                match[best] = r
                free.remove(best)
    kept = {r["id"] for r in match.values()}
    now = utcnow()
    for pos, t in enumerate(want):
        if t in match:
            conn.execute("UPDATE entries SET text=?, norm=?, position=?, item_id=? WHERE id=?",
                         (t, _norm(t), pos, item_id, match[t]["id"]))
        else:
            conn.execute("INSERT INTO entries(id,owner,item_id,text,norm,position,created_at)"
                         " VALUES (?,?,?,?,?,?,?)", (new_id(), owner, item_id, t, _norm(t), pos, now))
    for r in old.values():
        if r["id"] not in kept and not r["done_at"]:
            conn.execute("DELETE FROM entries WHERE id=?", (r["id"],))
        elif r["id"] not in kept:  # a done entry the note no longer names: keep it, after the rest
            conn.execute("UPDATE entries SET item_id=?, position=? WHERE id=?",
                         (item_id, len(want) + r["position"], r["id"]))
    return for_item(conn, item_id)


def set_done(conn, entry_id, done: bool) -> dict:
    if conn.execute("UPDATE entries SET done_at=? WHERE id=?",
                    (utcnow() if done else None, entry_id)).rowcount == 0:
        raise KeyError(entry_id)
    return _view(conn.execute("SELECT * FROM entries WHERE id=?", (entry_id,)).fetchone())
