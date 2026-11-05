import json
import re
import sqlite3
from dataclasses import dataclass

_TOKEN = re.compile(r"\w+")


@dataclass
class SearchHit:
    item_id: str
    title: str
    snippet: str
    source_url: str | None
    locator: str | None
    provenance: str
    kind: str
    score: float


def fts_query(q: str) -> str | None:
    """Quote every word (neutralises FTS operators/syntax); prefix-match the last one."""
    toks = _TOKEN.findall(q)
    if not toks:
        return None
    return " ".join(f'"{t}"' for t in toks[:-1]) + (" " if len(toks) > 1 else "") + f'"{toks[-1]}"*'


def search(services, query: str, *, limit: int = 10, filters: dict | None = None) -> list[SearchHit]:
    match = fts_query(query)
    if match is None:
        return []
    where, args = "", []
    for col in ("kind", "provenance"):
        if filters and filters.get(col):
            where += f" AND k.{col}=?"
            args.append(filters[col])
    try:
        rows = services.conn.execute(
            "SELECT k.id, k.title, k.provenance, k.kind, k.segment_refs, s.url, bm25(items_fts) AS r,"
            " snippet(items_fts, 1, '[', ']', '...', 16) AS snip"
            " FROM items_fts JOIN knowledge_items k ON k.rowid = items_fts.rowid"
            " LEFT JOIN sources s ON s.id = k.source_id"
            f" WHERE items_fts MATCH ? AND k.deleted_at IS NULL{where} ORDER BY r LIMIT ?",
            (match, *args, limit)).fetchall()
    except sqlite3.OperationalError:
        return []
    out = []
    for r in rows:
        refs = json.loads(r["segment_refs"] or "[]")
        loc = None
        if refs:
            seg = services.conn.execute("SELECT locator FROM segments WHERE id=?", (refs[0],)).fetchone()
            loc = seg["locator"] if seg else None
        out.append(SearchHit(r["id"], r["title"], r["snip"], r["url"], loc, r["provenance"], r["kind"], -r["r"]))
    return out
