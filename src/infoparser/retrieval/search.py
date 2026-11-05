"""Search: FTS (items + segments) and, when an embedder with vectors exists, cosine (items +
segments), fused with RRF, per-source capped, optionally reranked. Every optional stage degrades,
never raises: `SearchResult.mode` is "hybrid" only if the vector path actually ran; failures land
in `warnings`. `egress` lists remote backends that received query text. `search()` returns just
the hits."""
import json
import re
from dataclasses import dataclass, field

from infoparser.domain.text import normalize
from infoparser.retrieval import vectors
from infoparser.retrieval.fusion import RRF_K, rrf

_TOKEN = re.compile(r"\w+")
OVERFETCH = 4       # vector over-fetch factor before post-filtering
CANDIDATES = 50     # per ranked list (FTS / cosine, items / segments)
RERANK_TOP = 20
PER_SOURCE_CAP = 2
TEXT_CAP = 1500


@dataclass
class SearchResult:
    """Hits plus how they were found, degradation warnings and remote backends used."""

    hits: list
    mode: str = "fts"  # "hybrid" | "fts"
    warnings: list[str] = field(default_factory=list)
    egress: list[str] = field(default_factory=list)


@dataclass
class SearchHit:  # pylint: disable=too-many-instance-attributes  # flat record
    """One result: an item or a raw segment, with its source and locator."""

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
    text: str = ""  # fuller text (item body / segment text, capped) for answer excerpts
    platform: str | None = None


STOPWORDS = frozenset("""a about above after again all also am an and any are as at be because been
before being below between both but by can could did do does doing down during each few for from
further had has have having he her here hers him his how i if in into is it its just me more most
my no nor not of off on once only or other our out over own same she should so some such than that
the their them then there these they this those through to too under until up very was we were what
when where which while who whom why will with would you your""".split())


def fts_query(q: str) -> str | None:
    """Quote every \\w+ token (neutralises FTS operators/syntax) and OR them (bm25 ranks). English
    stopwords are dropped unless every token is one; the last kept token is prefix-matched only if
    it is a content word longer than 2 chars (so "and"* can never widen to "android")."""
    toks = _TOKEN.findall(q)
    if not toks:
        return None
    content = [t for t in toks if t.lower() not in STOPWORDS]
    use = content or toks
    last = use[-1]
    prefix = bool(content) and len(last) > 2
    quoted = [f'"{t}"' for t in use[:-1]] + [f'"{last}"' + ("*" if prefix else "")]
    return " OR ".join(quoted)


_FILTERS = {"kind": "k.kind", "provenance": "k.provenance", "platform": "s.platform"}


def _item_where(filters):
    where, args = "", []
    for name, col in _FILTERS.items():
        if name in filters:
            where += f" AND {col}=?"
            args.append(filters[name])
    if "since" in filters:
        where += " AND k.created_at>=?"
        args.append(filters["since"])
    if "topic" in filters:
        where += (" AND EXISTS (SELECT 1 FROM item_topics it JOIN topics t ON t.id=it.topic_id"
                  " WHERE it.item_id=k.id AND t.name=?)")
        args.append(normalize(filters["topic"]))
    return where, args


# a source whose items all got soft-deleted must not leak through its raw segments
_LIVE_SOURCE = (" AND NOT (EXISTS (SELECT 1 FROM knowledge_items x WHERE x.source_id=g.source_id)"
                " AND NOT EXISTS (SELECT 1 FROM knowledge_items x WHERE x.source_id=g.source_id"
                " AND x.deleted_at IS NULL))")


def _seg_where(filters):
    """`since` = ingestion time: items use created_at, raw segments use their source's
    fetched_at."""
    where, args = _LIVE_SOURCE, []
    if "platform" in filters:
        where += " AND s.platform=?"
        args.append(filters["platform"])
    if "since" in filters:
        where += " AND s.fetched_at>=?"
        args.append(filters["since"])
    return where, args


_ITEM_ONLY = {"kind", "provenance", "topic"}  # filters that exclude raw segments

_ITEM_COLS = ("k.id, k.title, k.body, k.provenance, k.kind, k.segment_refs, k.source_id,"
              " s.url, s.platform")


def _item_hit(services, r, snip, score):
    refs = json.loads(r["segment_refs"] or "[]")
    loc = None
    if refs:
        seg = services.conn.execute("SELECT locator FROM segments WHERE id=?",
                                    (refs[0],)).fetchone()
        loc = seg["locator"] if seg else None
    return SearchHit(r["id"], r["title"], snip, r["url"], loc, r["provenance"], r["kind"], score,
                     source_id=r["source_id"], text=f"{r['title']}\n{r['body'] or ''}"[:TEXT_CAP],
                     platform=r["platform"])


def _seg_hit(r, snip, score):
    return SearchHit(None, r["title"] or "", snip, r["url"], r["locator"], None, "segment", score,
                     r["id"], r["source_id"], text=(r["text"] or "")[:TEXT_CAP],
                     platform=r["platform"])


def _fts_items(services, match, filters, n):
    where, args = _item_where(filters)
    rows = services.conn.execute(
        f"SELECT {_ITEM_COLS}, bm25(items_fts) AS r,"
        " snippet(items_fts, 1, '[', ']', '...', 16) AS snip"
        " FROM items_fts JOIN knowledge_items k ON k.rowid = items_fts.rowid"
        " LEFT JOIN sources s ON s.id = k.source_id"
        f" WHERE items_fts MATCH ? AND k.deleted_at IS NULL{where} ORDER BY r LIMIT ?",
        (match, *args, n)).fetchall()
    return [_item_hit(services, r, r["snip"], -r["r"]) for r in rows]


def _fts_segments(services, match, filters, n):
    where, args = _seg_where(filters)
    rows = services.conn.execute(
        "SELECT g.id, g.source_id, g.locator, g.text, s.url, s.title, s.platform,"
        " bm25(segments_fts) AS r,"
        " snippet(segments_fts, 0, '[', ']', '...', 16) AS snip"
        " FROM segments_fts JOIN segments g ON g.id = segments_fts.rowid"
        " JOIN sources s ON s.id = g.source_id WHERE segments_fts MATCH ?"
        f"{where} ORDER BY r LIMIT ?",
        (match, *args, n)).fetchall()
    return [_seg_hit(r, r["snip"], -r["r"]) for r in rows]


def _fts_only(services, match, filters, limit):
    """FTS path: item hits, then at most one raw-segment hit per source not already represented
    by an item."""
    out = _fts_items(services, match, filters, limit)
    if (set(filters) & _ITEM_ONLY) or len(out) >= limit:
        return out
    seen, best = {h.source_id for h in out}, {}
    for h in _fts_segments(services, match, filters, CANDIDATES):
        if h.source_id not in seen and h.source_id not in best:
            best[h.source_id] = h
    return out + list(best.values())[: limit - len(out)]


def _hydrate_items(services, ids, filters):
    if not ids:
        return {}
    where, args = _item_where(filters)
    q = ",".join("?" * len(ids))
    rows = services.conn.execute(
        f"SELECT {_ITEM_COLS} FROM knowledge_items k LEFT JOIN sources s ON s.id=k.source_id"
        f" WHERE k.id IN ({q}) AND k.deleted_at IS NULL{where}", (*ids, *args)).fetchall()
    return {r["id"]: _item_hit(services, r, (r["body"] or "")[:200], 0.0) for r in rows}


def _hydrate_segments(services, ids, filters):
    if not ids or (set(filters) & _ITEM_ONLY):
        return {}
    where, args = _seg_where(filters)
    q = ",".join("?" * len(ids))
    rows = services.conn.execute(
        "SELECT g.id, g.source_id, g.locator, g.text, s.url, s.title, s.platform FROM segments g"
        f" JOIN sources s ON s.id=g.source_id WHERE g.id IN ({q}){where}",
        (*[int(i) for i in ids], *args)).fetchall()
    return {str(r["id"]): _seg_hit(r, (r["text"] or "")[:200], 0.0) for r in rows}


def _egress(res, backend):
    if backend.locality == "remote" and backend.name not in res.egress:
        res.egress.append(backend.name)


def _vector_lists(services, query, filters, res):
    """-> (item_hits_ranked, segment_hits_ranked) or None when the vector path is unavailable."""
    emb = services.registry.first("embed")
    if emb is None:
        return None
    _egress(res, emb)  # recorded before the call: text leaves even if the call then fails
    try:
        er = emb.embed([query])
        qv = er.vectors[0]
        over = CANDIDATES * OVERFETCH  # filters apply after cosine, so over-fetch
        iv, sv = (
            [(i, sc) for i, sc in vectors.cosine_topk(services.conn, er.model_id, qv, over, kind)
             if sc > 0] for kind in ("item", "segment"))
    except Exception as e:  # pylint: disable=broad-exception-caught  # embedder down, bad vectors: FTS still answers
        res.warnings.append(f"vector search unavailable ({type(e).__name__}: {e}); using FTS only")
        return None
    if not services.conn.execute("SELECT 1 FROM embeddings WHERE model_id=? LIMIT 1",
                                 (er.model_id,)).fetchone():
        res.warnings.append(f"no vectors for embedding model {er.model_id!r}; "
                            "run `infoparser reindex`; using FTS only")
        return None
    items = _hydrate_items(services, [i for i, _ in iv], filters)
    segs = _hydrate_segments(services, [i for i, _ in sv], filters)
    return ([items[i] for i, _ in iv if i in items][:CANDIDATES],
            [segs[i] for i, _ in sv if i in segs][:CANDIDATES])


def _cap_per_source(hits, cap):
    n, out = {}, []
    for h in hits:
        key = h.source_id or id(h)
        if n.get(key, 0) < cap:
            n[key] = n.get(key, 0) + 1
            out.append(h)
    return out


def _rerank(services, query, hits, res):
    rr = services.registry.first("rerank")
    if rr is None or not hits:
        return hits
    top = hits[:RERANK_TOP]
    _egress(res, rr)
    try:
        scores = rr.rerank(query, [f"{h.title}\n{h.text or h.snippet}" for h in top])
        if len(scores) != len(top):
            raise ValueError("rerank returned wrong number of scores")
    except Exception as e:  # pylint: disable=broad-exception-caught  # degrade: keep FTS/vector order
        res.warnings.append(f"rerank skipped ({type(e).__name__}: {e})")
        return hits
    order = sorted(range(len(top)), key=lambda i: (-scores[i], i))
    for i in order:
        top[i].score = float(scores[i])
    return [top[i] for i in order] + hits[RERANK_TOP:]


def _key(h):
    return f"i:{h.item_id}" if h.item_id else f"s:{h.segment_id}"


def _fused(services, match, filters, vec, per_source):
    """FTS and vector lists fused with RRF, then capped per source."""
    fi = _fts_items(services, match, filters, CANDIDATES) if match else []
    only_items = bool(set(filters) & _ITEM_ONLY)
    fs = _fts_segments(services, match, filters, CANDIDATES) if match and not only_items else []
    by_key = {}
    for h in [*vec[1], *vec[0], *fs, *fi]:  # FTS hits last: their highlighted snippets win
        by_key[_key(h)] = h
    fused = rrf([[_key(h) for h in lst] for lst in (fi, fs, *vec)], k=RRF_K)
    ranked = []
    for key, score in fused:
        by_key[key].score = score
        ranked.append(by_key[key])
    return _cap_per_source(ranked, per_source)


def search_ex(services, query: str, *, limit: int = 10,  # pylint: disable=too-many-arguments  # public keyword-only search options
              filters: dict | None = None, mode: str = "hybrid",
              per_source: int = PER_SOURCE_CAP) -> SearchResult:
    """Search saved knowledge; never raises for an unavailable optional stage."""
    res = SearchResult([])
    match = fts_query(query)
    filters = {k: v for k, v in (filters or {}).items() if v}
    vec = _vector_lists(services, query, filters, res) if mode == "hybrid" else None
    if vec is None:
        if match is not None:
            res.hits = _cap_per_source(_fts_only(services, match, filters, limit * 2), per_source)
            res.hits = _rerank(services, query, res.hits, res)[:limit]
        return res
    res.mode = "hybrid"
    ranked = _rerank(services, query, _fused(services, match, filters, vec, per_source), res)
    res.hits = ranked[:limit]
    return res


def search(services, query: str, *, limit: int = 10, filters: dict | None = None,
           mode: str = "hybrid") -> list[SearchHit]:
    """Like `search_ex` but returns only the hits."""
    return search_ex(services, query, limit=limit, filters=filters, mode=mode).hits
