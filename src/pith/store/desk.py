"""Durable contextual groups, with revision-checked atomic organization updates."""
from __future__ import annotations

import re

from pith.store.db import transaction

ICONS = frozenset(("bookmark", "database", "terminal", "book", "compass", "layers"))
_GROUP_ID = re.compile(r"[A-Za-z0-9_-]{1,80}")
_ITEM_ID = re.compile(r"[A-Za-z0-9]{1,64}")
MAX_GROUPS = 200
MAX_MEMBERSHIPS = 10_000


class ConflictError(Exception):
    """Another browser changed the desk since this snapshot was loaded."""


def read(conn) -> dict:
    """Read one consistent snapshot, excluding soft-deleted group members."""
    with transaction(conn):
        revision = conn.execute("SELECT revision FROM desk_state WHERE singleton=1").fetchone()[0]
        groups = []
        for row in conn.execute("SELECT * FROM desk_groups ORDER BY position, id"):
            members = conn.execute(
                "SELECT k.id, k.title, k.kind, k.created_at, k.shelf_id, src.content_type"
                " FROM desk_group_items d JOIN knowledge_items k ON k.id=d.item_id"
                " LEFT JOIN sources src ON src.id=k.source_id"
                " WHERE d.group_id=? AND k.deleted_at IS NULL ORDER BY d.position, k.id",
                (row["id"],)).fetchall()
            items = [{"id": r["id"], "title": r["title"] or "Untitled", "kind": r["kind"],
                      "created_at": r["created_at"], "type": r["content_type"],
                      "shelf": r["shelf_id"] or "other"} for r in members]
            groups.append({"id": row["id"], "title": row["title"],
                           "description": row["description"], "icon": row["icon"],
                           "focused": bool(row["focused"]), "item_ids": [r["id"] for r in items],
                           "items": items})
        return {"revision": revision, "groups": groups}


def _text(group, key: str, cap: int, *, required: bool = False) -> str:
    value = group.get(key)
    if not isinstance(value, str) or len(value) > cap or (required and not value.strip()):
        raise ValueError(f"{key} must be {'a non-empty' if required else 'a'} string of at most {cap} characters")
    return value.strip()


def _validate(body) -> tuple[int, list[dict]]:
    if not isinstance(body, dict) or set(body) != {"revision", "groups"}:
        raise ValueError("expected {revision, groups}")
    revision, groups = body["revision"], body["groups"]
    if type(revision) is not int or revision < 0:
        raise ValueError("revision must be a non-negative integer")
    if not isinstance(groups, list) or len(groups) > MAX_GROUPS:
        raise ValueError(f"groups must be a list of at most {MAX_GROUPS} groups")
    clean, seen, member_count = [], set(), 0
    for group in groups:
        if not isinstance(group, dict) or set(group) != {
                "id", "title", "description", "icon", "focused", "item_ids"}:
            raise ValueError("expected group {id, title, description, icon, focused, item_ids}")
        gid = group["id"]
        if not isinstance(gid, str) or not _GROUP_ID.fullmatch(gid) or gid in seen:
            raise ValueError("group ids must be unique and contain only letters, numbers, underscores or hyphens")
        seen.add(gid)
        if not isinstance(group["icon"], str) or group["icon"] not in ICONS:
            raise ValueError("unknown group icon")
        if type(group["focused"]) is not bool:
            raise ValueError("focused must be true or false")
        ids = group["item_ids"]
        if not isinstance(ids, list) or any(not isinstance(i, str) or not _ITEM_ID.fullmatch(i) for i in ids):
            raise ValueError("item_ids must be a list of note ids")
        member_count += len(ids)
        if len(set(ids)) != len(ids):
            raise ValueError("a note may appear only once within a group")
        if member_count > MAX_MEMBERSHIPS:
            raise ValueError(f"desk supports at most {MAX_MEMBERSHIPS} memberships")
        clean.append({**group, "title": _text(group, "title", 80, required=True),
                      "description": _text(group, "description", 140)})
    return revision, clean


def replace(conn, body) -> dict:
    """Replace group organization atomically; reject stale writes without changing data."""
    revision, groups = _validate(body)
    with transaction(conn):
        current = conn.execute("SELECT revision FROM desk_state WHERE singleton=1").fetchone()[0]
        if revision != current:
            raise ConflictError("Your desk changed in another window. Reload it before making changes.")
        ids = {iid for group in groups for iid in group["item_ids"]}
        for iid in ids:
            if conn.execute("SELECT 1 FROM knowledge_items WHERE id=? AND deleted_at IS NULL"
                            " AND kind IN ('note','summary')", (iid,)).fetchone() is None:
                raise ValueError("One of the chosen notes is unavailable. Reload your desk and try again.")
        conn.execute("DELETE FROM desk_groups")
        for position, group in enumerate(groups):
            conn.execute("INSERT INTO desk_groups(id,title,description,icon,position,focused)"
                         " VALUES (?,?,?,?,?,?)", (group["id"], group["title"], group["description"],
                                                  group["icon"], position, int(group["focused"])))
            conn.executemany("INSERT INTO desk_group_items(group_id,item_id,position) VALUES (?,?,?)",
                             [(group["id"], iid, i) for i, iid in enumerate(group["item_ids"])])
        conn.execute("UPDATE desk_state SET revision=revision+1 WHERE singleton=1")
        return read(conn)


def rebind(conn, replaced_ids: list[str], replacement_id: str | None) -> None:
    """Carry organization across note reprocessing inside the knowledge transaction.

    A source's generated note can receive a new row id. Keep its chosen contexts
    at the same positions; an explicit note deletion does not call this helper.
    """
    if not replaced_ids:
        return
    marks = ",".join("?" for _ in replaced_ids)
    with transaction(conn):
        rows = conn.execute(
            f"SELECT group_id, position FROM desk_group_items WHERE item_id IN ({marks})"
            " ORDER BY group_id, position", replaced_ids).fetchall()
        if not rows:
            return
        if replacement_id:
            conn.executemany(
                "INSERT OR IGNORE INTO desk_group_items(group_id,item_id,position) VALUES (?,?,?)",
                [(r["group_id"], replacement_id, r["position"]) for r in rows])
        conn.execute(f"DELETE FROM desk_group_items WHERE item_id IN ({marks})", replaced_ids)
        conn.execute("UPDATE desk_state SET revision=revision+1 WHERE singleton=1")
