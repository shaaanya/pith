"""Knowledge store. Items are replaced (soft-deleted + versioned) on reprocess unless user_edited.
FTS rows (items_fts rowid = knowledge_items rowid, segments_fts rowid = segments.id) are kept in the
same transaction as the writes."""
import json
import sqlite3

from infoparser.domain.models import Candidate, SegmentIn
from infoparser.ids import new_id, utcnow
from infoparser.store.db import transaction

_EDITABLE = {"title", "body", "data"}


def save_source(conn, *, url, title, author, platform, content_type, blob_sha256, text_sha256, extractor) -> str:
    sid = new_id()
    conn.execute(
        "INSERT INTO sources(id,url,title,author,platform,content_type,fetched_at,blob_sha256,text_sha256,extractor)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)",
        (sid, url, title, author, platform, content_type, utcnow(), blob_sha256, text_sha256, extractor))
    return sid


def save_segments(conn, source_id, segs: list[SegmentIn]) -> list[int]:
    with transaction(conn):
        for (old,) in conn.execute("SELECT id FROM segments WHERE source_id=?", (source_id,)).fetchall():
            conn.execute("DELETE FROM segments_fts WHERE rowid=?", (old,))
        conn.execute("DELETE FROM segments WHERE source_id=?", (source_id,))
        ids = []
        for s in segs:
            cur = conn.execute("INSERT INTO segments(source_id,idx,text,locator) VALUES (?,?,?,?)",
                               (source_id, s.idx, s.text, s.locator))
            conn.execute("INSERT INTO segments_fts(rowid,text) VALUES (?,?)", (cur.lastrowid, s.text))
            ids.append(cur.lastrowid)
    return ids


def _snapshot(conn, row, reason, now):
    conn.execute("INSERT INTO knowledge_versions(item_id,version,title,body,data_json,saved_at,reason) VALUES (?,?,?,?,?,?,?)",
                 (row["id"], row["version"], row["title"], row["body"], row["data_json"], now, reason))


def _fts_set(conn, rowid, title, body):
    conn.execute("DELETE FROM items_fts WHERE rowid=?", (rowid,))
    conn.execute("INSERT INTO items_fts(rowid,title,body) VALUES (?,?,?)", (rowid, title, body))


def save_items(conn, source_id, candidates: list[Candidate], extracted_by, segment_ids: list[int]) -> list[str]:
    now, ids = utcnow(), []
    with transaction(conn):
        old = conn.execute("SELECT rowid AS rid, * FROM knowledge_items WHERE source_id=? AND user_edited=0"
                           " AND deleted_at IS NULL", (source_id,)).fetchall()
        for r in old:
            _snapshot(conn, r, "reprocess", now)
            conn.execute("UPDATE knowledge_items SET deleted_at=?, updated_at=? WHERE id=?", (now, now, r["id"]))
            conn.execute("DELETE FROM items_fts WHERE rowid=?", (r["rid"],))
        for c in candidates:
            iid = new_id()
            data = {**c.data, **({"evidence": c.evidence} if c.evidence else {}),
                    **({"entities": c.entities} if c.entities else {}), **({"topics": c.topics} if c.topics else {})}
            ref = [segment_ids[c.segment_idx]] if c.segment_idx is not None and 0 <= c.segment_idx < len(segment_ids) else []
            cur = conn.execute(
                "INSERT INTO knowledge_items(id,kind,title,body,data_json,provenance,confidence,source_id,segment_refs,"
                "extracted_by,flagged,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (iid, c.kind, c.title, c.body, json.dumps(data), c.provenance, c.confidence, source_id,
                 json.dumps(ref), extracted_by, int("flag" in c.data), now, now))
            _fts_set(conn, cur.lastrowid, c.title, c.body)
            ids.append(iid)
    return ids


def get_item(conn, item_id) -> dict | None:
    r = conn.execute("SELECT * FROM knowledge_items WHERE id=?", (item_id,)).fetchone()
    if r is None:
        return None
    d = dict(r)
    d["data"] = json.loads(d.pop("data_json") or "{}")
    d["segment_refs"] = json.loads(d["segment_refs"] or "[]")
    return d


def update_item(conn, item_id, **fields) -> None:
    if bad := set(fields) - _EDITABLE:
        raise ValueError(f"cannot edit {sorted(bad)}")
    now = utcnow()
    with transaction(conn):
        r = conn.execute("SELECT rowid AS rid, * FROM knowledge_items WHERE id=?", (item_id,)).fetchone()
        if r is None:
            raise KeyError(item_id)
        _snapshot(conn, r, "user_edit", now)
        title, body = fields.get("title", r["title"]), fields.get("body", r["body"])
        data_json = json.dumps(fields["data"]) if "data" in fields else r["data_json"]
        conn.execute("UPDATE knowledge_items SET title=?, body=?, data_json=?, user_edited=1, version=version+1,"
                     " updated_at=? WHERE id=?", (title, body, data_json, now, item_id))
        if r["deleted_at"] is None:
            _fts_set(conn, r["rid"], title, body)


def delete_item(conn, item_id) -> None:
    now = utcnow()
    with transaction(conn):
        r = conn.execute("SELECT rowid AS rid FROM knowledge_items WHERE id=?", (item_id,)).fetchone()
        if r is None:
            raise KeyError(item_id)
        conn.execute("UPDATE knowledge_items SET deleted_at=?, updated_at=? WHERE id=?", (now, now, item_id))
        conn.execute("DELETE FROM items_fts WHERE rowid=?", (r["rid"],))
