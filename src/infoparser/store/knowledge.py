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
    """Upsert by (source_id, idx): existing segments keep their ids (so preserved items' segment_refs stay
    valid on reprocess); segments no longer present are deleted and their ids dropped from item refs."""
    with transaction(conn):
        have = {r["idx"]: r["id"] for r in conn.execute("SELECT id, idx FROM segments WHERE source_id=?", (source_id,))}
        ids = []
        for s in segs:
            if s.idx in have:
                sid = have[s.idx]
                conn.execute("UPDATE segments SET text=?, locator=? WHERE id=?", (s.text, s.locator, sid))
                conn.execute("DELETE FROM segments_fts WHERE rowid=?", (sid,))
            else:
                sid = conn.execute("INSERT INTO segments(source_id,idx,text,locator) VALUES (?,?,?,?)",
                                   (source_id, s.idx, s.text, s.locator)).lastrowid
            conn.execute("INSERT INTO segments_fts(rowid,text) VALUES (?,?)", (sid, s.text))
            ids.append(sid)
        gone = {i for idx, i in have.items() if idx not in {s.idx for s in segs}}
        for g in gone:
            conn.execute("DELETE FROM segments_fts WHERE rowid=?", (g,))
            conn.execute("DELETE FROM segments WHERE id=?", (g,))
        if gone:
            for r in conn.execute("SELECT id, segment_refs FROM knowledge_items WHERE source_id=?", (source_id,)).fetchall():
                refs = json.loads(r["segment_refs"] or "[]")
                if gone & set(refs):
                    conn.execute("UPDATE knowledge_items SET segment_refs=? WHERE id=?",
                                 (json.dumps([x for x in refs if x not in gone]), r["id"]))
    return ids


def _purge_links(conn, item_ids) -> None:
    """Drop topic/entity links, relations (either side) and vectors of items that stop being live."""
    for i in item_ids:
        conn.execute("DELETE FROM item_topics WHERE item_id=?", (i,))
        conn.execute("DELETE FROM item_entities WHERE item_id=?", (i,))
        conn.execute("DELETE FROM relations WHERE item_a=? OR item_b=?", (i, i))
        conn.execute("DELETE FROM embeddings WHERE owner_type='item' AND owner_id=?", (i,))


def _snapshot(conn, row, reason, now):
    conn.execute("INSERT INTO knowledge_versions(item_id,version,title,body,data_json,saved_at,reason) VALUES (?,?,?,?,?,?,?)",
                 (row["id"], row["version"], row["title"], row["body"], row["data_json"], now, reason))


def _fts_set(conn, rowid, title, body):
    conn.execute("DELETE FROM items_fts WHERE rowid=?", (rowid,))
    conn.execute("INSERT INTO items_fts(rowid,title,body) VALUES (?,?,?)", (rowid, title, body))


def save_items(conn, source_id, candidates: list[Candidate], extracted_by, segment_ids: list[int]) -> list[str]:
    now, ids = utcnow(), []
    with transaction(conn):
        by_idx = {}  # segment idx -> id, looked up from the idx column (not list position)
        if segment_ids:
            q = ",".join("?" * len(segment_ids))
            by_idx = {r["idx"]: r["id"] for r in conn.execute(f"SELECT id, idx FROM segments WHERE id IN ({q})", segment_ids)}
        old = conn.execute("SELECT rowid AS rid, * FROM knowledge_items WHERE source_id=? AND user_edited=0"
                           " AND deleted_at IS NULL", (source_id,)).fetchall()
        for r in old:
            _snapshot(conn, r, "reprocess", now)
            conn.execute("UPDATE knowledge_items SET deleted_at=?, updated_at=? WHERE id=?", (now, now, r["id"]))
            conn.execute("DELETE FROM items_fts WHERE rowid=?", (r["rid"],))
        _purge_links(conn, [r["id"] for r in old])
        for c in candidates:
            iid = new_id()
            # entities/topics live in their tables (pipeline.entities.apply), not in data_json
            data = {**c.data, **({"evidence": c.evidence} if c.evidence else {})}
            ref = [by_idx[c.segment_idx]] if c.segment_idx in by_idx else []
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


_KEEP = ("evidence",)


def update_item(conn, item_id, **fields) -> None:
    """Edit title/body/data. `data` is MERGED over the stored data: evidence is kept
    unless the new data names it explicitly; other stored keys are replaced by the new dict."""
    if bad := set(fields) - _EDITABLE:
        raise ValueError(f"cannot edit {sorted(bad)}")
    now = utcnow()
    with transaction(conn):
        r = conn.execute("SELECT rowid AS rid, * FROM knowledge_items WHERE id=?", (item_id,)).fetchone()
        if r is None:
            raise KeyError(item_id)
        _snapshot(conn, r, "user_edit", now)
        title, body = fields.get("title", r["title"]), fields.get("body", r["body"])
        data_json = r["data_json"]
        if "data" in fields:
            old = json.loads(r["data_json"] or "{}")
            data_json = json.dumps({**{k: old[k] for k in _KEEP if k in old}, **fields["data"]})
        conn.execute("UPDATE knowledge_items SET title=?, body=?, data_json=?, user_edited=1, version=version+1,"
                     " updated_at=? WHERE id=?", (title, body, data_json, now, item_id))
        if r["deleted_at"] is None:
            _fts_set(conn, r["rid"], title, body)
        conn.execute("DELETE FROM embeddings WHERE owner_type='item' AND owner_id=?", (item_id,))  # stale vector


def delete_item(conn, item_id) -> None:
    now = utcnow()
    with transaction(conn):
        r = conn.execute("SELECT rowid AS rid FROM knowledge_items WHERE id=?", (item_id,)).fetchone()
        if r is None:
            raise KeyError(item_id)
        conn.execute("UPDATE knowledge_items SET deleted_at=?, updated_at=? WHERE id=? AND deleted_at IS NULL",
                     (now, now, item_id))
        conn.execute("DELETE FROM items_fts WHERE rowid=?", (r["rid"],))
        _purge_links(conn, [item_id])
