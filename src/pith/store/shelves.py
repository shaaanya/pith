"""Shelves (what a note is useful for) and where each note sits.

Placement lives on the note row: shelf_id (null until placed, read as "other"), placement_by
(user | model | rule | default), placement_why, placement_model, placed_at. A user's own move is never
overwritten by automation (see knowledge.save_items for reprocess)."""
import re

from pith.ids import utcnow

OTHER = "other"
BY = ("user", "model", "rule", "default")


def _shelf(r) -> dict:
    return {"id": r["id"], "name": r["name"], "blurb": r["blurb"], "todo": bool(r["todo"]),
            "done_label": r["done_label"], "builtin": bool(r["builtin"]), "position": r["position"]}


def list_shelves(conn) -> list[dict]:
    """Built-ins first (their fixed order), then custom shelves in creation order."""
    return [_shelf(r) for r in conn.execute("SELECT * FROM shelves ORDER BY position, created_at")]


def _get(conn, shelf_id):
    r = conn.execute("SELECT * FROM shelves WHERE id=?", (shelf_id,)).fetchone()
    if r is None:
        raise KeyError(shelf_id)
    return r


def _clean(name) -> str:
    name = " ".join(str(name or "").split())
    if not name:
        raise ValueError("a shelf needs a name")
    return name


def _taken(conn, name, except_id=None) -> bool:
    return conn.execute("SELECT 1 FROM shelves WHERE lower(name)=lower(?) AND id IS NOT ?",
                        (name, except_id)).fetchone() is not None


def create_shelf(conn, name: str, blurb: str = "") -> dict:
    name = _clean(name)
    if _taken(conn, name):
        raise ValueError(f"a shelf named {name!r} already exists")
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "shelf"
    sid, n = base, 2
    while conn.execute("SELECT 1 FROM shelves WHERE id=?", (sid,)).fetchone():
        sid, n = f"{base}-{n}", n + 1
    pos = conn.execute("SELECT coalesce(max(position),0)+1 FROM shelves").fetchone()[0]
    conn.execute("INSERT INTO shelves(id,name,blurb,todo,done_label,builtin,position,created_at)"
                 " VALUES (?,?,?,1,'Done',0,?,?)", (sid, name, (blurb or "").strip(), pos, utcnow()))
    return _shelf(_get(conn, sid))


def update_shelf(conn, shelf_id, *, name=None, blurb=None) -> dict:
    cur = _get(conn, shelf_id)
    if name is not None:
        if cur["builtin"]:
            raise ValueError("built-in shelves keep their names")
        name = _clean(name)
        if _taken(conn, name, shelf_id):
            raise ValueError(f"a shelf named {name!r} already exists")
        conn.execute("UPDATE shelves SET name=? WHERE id=?", (name, shelf_id))
    if blurb is not None:
        conn.execute("UPDATE shelves SET blurb=? WHERE id=?", (str(blurb).strip(), shelf_id))
    return _shelf(_get(conn, shelf_id))


def delete_shelf(conn, shelf_id) -> None:
    """Custom shelves only; their notes move to Other (nothing is deleted)."""
    if _get(conn, shelf_id)["builtin"]:
        raise ValueError("built-in shelves cannot be deleted")
    # the notes did not choose Other: say so, and let a later placement pick a better home
    conn.execute("UPDATE knowledge_items SET shelf_id=?, placement_by='default',"
                 " placement_why='Its shelf was deleted' WHERE shelf_id=?", (OTHER, shelf_id))
    conn.execute("DELETE FROM shelves WHERE id=?", (shelf_id,))


def set_placement(conn, item_id, shelf_id, by, why, model=None) -> None:
    assert by in BY
    _get(conn, shelf_id)
    conn.execute("UPDATE knowledge_items SET shelf_id=?, placement_by=?, placement_why=?,"
                 " placement_model=?, placed_at=? WHERE id=?",
                 (shelf_id, by, why, model, utcnow(), item_id))


def placement_of(row) -> dict:
    return {"shelf": row["shelf_id"] or OTHER, "by": row["placement_by"],
            "why": row["placement_why"]}
