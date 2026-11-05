"""Embedding index maintenance. Best-effort: no embedder configured -> everything is a no-op (FTS still works)."""
from infoparser.retrieval import vectors


def _model_id(embedder) -> str:
    return embedder.embed(["."]).model_id  # the port reports the id only alongside vectors


def _owners(conn, model_id: str, only_missing: bool):
    q = ("SELECT 'segment' AS t, CAST(g.id AS TEXT) AS id, g.text AS text FROM segments g"
         " UNION ALL SELECT 'item', k.id, k.title || char(10) || k.body FROM knowledge_items k"
         " WHERE k.deleted_at IS NULL")
    rows = conn.execute(q).fetchall()
    if not only_missing:
        return rows
    have = {(r[0], r[1]) for r in conn.execute("SELECT owner_type, owner_id FROM embeddings WHERE model_id=?",
                                                (model_id,))}
    return [r for r in rows if (r["t"], r["id"]) not in have]


def _embed(services, embedder, model_id, only_missing, batch) -> int:
    rows = _owners(services.conn, model_id, only_missing)
    n = 0
    for i in range(0, len(rows), batch):
        part = rows[i:i + batch]
        res = embedder.embed([r["text"] or "" for r in part])
        for t in ("segment", "item"):
            sel = [(r["id"], v) for r, v in zip(part, res.vectors) if r["t"] == t]
            if sel:
                vectors.put(services.conn, t, [x for x, _ in sel], res.model_id, [v for _, v in sel])
        n += len(part)
    return n


def embed_pending(services, batch: int = 32) -> int:
    """Embed segments and live items lacking a vector for the active model. Returns count embedded."""
    emb = services.registry.first("embed")
    if emb is None:
        return 0
    return _embed(services, emb, _model_id(emb), True, batch)


def reindex(services, *, prune_old: bool = False) -> int:
    """Rebuild every vector for the active embedding model; optionally delete other models' rows."""
    emb = services.registry.first("embed")
    if emb is None:
        return 0
    mid = _model_id(emb)
    with services.conn:  # autocommit connection: single statements
        services.conn.execute("DELETE FROM embeddings WHERE model_id=?", (mid,))
        if prune_old:
            services.conn.execute("DELETE FROM embeddings WHERE model_id<>?", (mid,))
    return _embed(services, emb, mid, False, 32)
