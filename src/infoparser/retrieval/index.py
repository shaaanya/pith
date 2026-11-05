"""Embedding index maintenance. Best-effort: no embedder configured -> everything is a no-op (FTS still works)."""
from infoparser.retrieval import vectors
from infoparser.store.db import transaction


def _model_id(embedder) -> str:
    """The port reports the model id only alongside vectors, so probe once per backend instance."""
    mid = getattr(embedder, "_ip_model_id", None)
    if mid is None:
        mid = embedder.embed(["."]).model_id
        try:
            embedder._ip_model_id = mid
        except AttributeError:  # slotted/frozen backend: just re-probe next time
            pass
    return mid


def _owners(conn, model_id: str, only_missing: bool):
    q = ("SELECT 'segment' AS t, CAST(g.id AS TEXT) AS id, g.text AS text FROM segments g"
         " UNION ALL SELECT 'item', k.id, k.title || char(10) || k.body FROM knowledge_items k"
         " WHERE k.deleted_at IS NULL")
    rows = [r for r in conn.execute(q) if (r["text"] or "").strip()]  # nothing to embed in blank text
    if not only_missing:
        return rows
    have = {(r[0], r[1]) for r in conn.execute("SELECT owner_type, owner_id FROM embeddings WHERE model_id=?",
                                                (model_id,))}
    return [r for r in rows if (r["t"], r["id"]) not in have]


def _compute(embedder, rows, batch):
    """-> [(owner_type, owner_id, model_id, vector)]; nothing is written here."""
    out = []
    for i in range(0, len(rows), batch):
        part = rows[i:i + batch]
        res = embedder.embed([r["text"] for r in part])
        out += [(r["t"], r["id"], res.model_id, v) for r, v in zip(part, res.vectors)]
    return out


def _store(conn, computed) -> None:
    for t in ("segment", "item"):
        for mid in {m for tt, _, m, _ in computed if tt == t}:
            sel = [(o, v) for tt, o, m, v in computed if tt == t and m == mid]
            vectors.put(conn, t, [o for o, _ in sel], mid, [v for _, v in sel])


def embed_pending(services, batch: int = 32) -> int:
    """Embed segments and live items lacking a vector for the active model. Returns count embedded."""
    emb = services.registry.first("embed")
    if emb is None:
        return 0
    computed = _compute(emb, _owners(services.conn, _model_id(emb), True), batch)
    _store(services.conn, computed)
    return len(computed)


def reindex(services, *, prune_old: bool = False) -> int:
    """Rebuild every vector for the active embedding model; optionally delete other models' rows.
    New vectors are computed first; the swap is one transaction, so a failing embedder loses nothing."""
    emb = services.registry.first("embed")
    if emb is None:
        return 0
    mid = _model_id(emb)
    computed = _compute(emb, _owners(services.conn, mid, False), 32)
    with transaction(services.conn):
        services.conn.execute("DELETE FROM embeddings WHERE model_id=?", (mid,))
        if prune_old:
            services.conn.execute("DELETE FROM embeddings WHERE model_id<>?", (mid,))
        _store(services.conn, computed)
    return len(computed)
