import json
import re
from dataclasses import dataclass

from infoparser.domain.text import normalize

_TOKEN = re.compile(r"\w+")


@dataclass
class SearchHit:
    item_id: str | None  # None for raw-segment hits (kind == "segment")
    title: str
    snippet: str
    source_url: str | None
    locator: str | None
    provenance: str | None
    kind: str
    score: float
    segment_id: int | None = None
    source_id: str | None = None


def fts_query(q: str) -> str | None:
    """Quote every word (neutralises FTS operators/syntax), OR them (bm25 ranks), prefix-match the last."""
    toks = _TOKEN.findall(q)
    if not toks:
        return None
    return " OR ".join([f'"{t}"' for t in toks[:-1]] + [f'"{toks[-1]}"*'])


_FILTERS = {"kind": "k.kind", "provenance": "k.provenance", "platform": "s.platform"}


def search(services, query: str, *, limit: int = 10, filters: dict | None = None) -> list[SearchHit]:
    match = fts_query(query)
    if match is None:
        return []
    filters = {k: v for k, v in (filters or {}).items() if v}
    where, args = "", []
    for name, col in _FILTERS.items():
        if name in filters:
            where += f" AND {col}=?"
            args.append(filters[name])
    if "topic" in filters:
        where += (" AND EXISTS (SELECT 1 FROM item_topics it JOIN topics t ON t.id=it.topic_id"
                  " WHERE it.item_id=k.id AND t.name=?)")
        args.append(normalize(filters["topic"]))
    rows = services.conn.execute(
        "SELECT k.id, k.title, k.provenance, k.kind, k.segment_refs, k.source_id, s.url, bm25(items_fts) AS r,"
        " snippet(items_fts, 1, '[', ']', '...', 16) AS snip"
        " FROM items_fts JOIN knowledge_items k ON k.rowid = items_fts.rowid"
        " LEFT JOIN sources s ON s.id = k.source_id"
        f" WHERE items_fts MATCH ? AND k.deleted_at IS NULL{where} ORDER BY r LIMIT ?",
        (match, *args, limit)).fetchall()
    out = []
    for r in rows:
        refs = json.loads(r["segment_refs"] or "[]")
        loc = None
        if refs:
            seg = services.conn.execute("SELECT locator FROM segments WHERE id=?", (refs[0],)).fetchone()
            loc = seg["locator"] if seg else None
        out.append(SearchHit(r["id"], r["title"], r["snip"], r["url"], loc, r["provenance"], r["kind"],
                             -r["r"], source_id=r["source_id"]))
    if filters or len(out) >= limit:  # item-only filters exclude raw segments
        return out
    seen = {h.source_id for h in out}
    best: dict[str, SearchHit] = {}
    for r in services.conn.execute(
            "SELECT g.id, g.source_id, g.locator, s.url, s.title, bm25(segments_fts) AS r,"
            " snippet(segments_fts, 0, '[', ']', '...', 16) AS snip"
            " FROM segments_fts JOIN segments g ON g.id = segments_fts.rowid"
            " JOIN sources s ON s.id = g.source_id WHERE segments_fts MATCH ? ORDER BY r", (match,)):
        if r["source_id"] in seen or r["source_id"] in best:
            continue
        best[r["source_id"]] = SearchHit(None, r["title"] or "", r["snip"], r["url"], r["locator"], None,
                                         "segment", -r["r"], r["id"], r["source_id"])
    return out + list(best.values())[: limit - len(out)]
