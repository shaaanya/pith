"""Near-duplicate / related detection, writing `relations`. Never raises for lack of an embedder.
Duplicates: cosine >= threshold when both items have vectors for the active model, else shingle
Jaccard >= 0.8 over title+body. Related (embeddings only): RELATED_COSINE <= cosine < threshold.
Items of the same source are skipped.
ponytail: compares each new item against all live items (O(N)); add an ANN/LSH shortlist if N
gets large."""
import re

from infoparser.retrieval import vectors
from infoparser.retrieval.index import _model_id

JACCARD = 0.8  # shingle Jaccard (no embeddings) for 'duplicate'
DUPLICATE_COSINE = 0.92
RELATED_COSINE = 0.75
_SHINGLE = 3


def _shingles(text: str) -> set:
    w = re.findall(r"\w+", (text or "").lower())
    return {tuple(w[i:i + _SHINGLE]) for i in range(max(1, len(w) - _SHINGLE + 1))} if w else set()


class _ShingleCache(dict):
    """item id -> shingle set of title+body, computed on first use."""

    def __init__(self, rows):
        super().__init__()
        self.rows = rows

    def __missing__(self, key):
        row = self.rows[key]
        self[key] = _shingles(f"{row['title']} {row['body']}")
        return self[key]


def _classify(a, b, vecs, shingles, threshold) -> tuple[float, str | None]:
    """-> (score, 'duplicate' | 'related' | None) for a pair, by cosine or shingle Jaccard."""
    if a in vecs and b in vecs:
        score = float(vecs[a] @ vecs[b])
        kind = "duplicate" if score >= threshold else "related" if score >= RELATED_COSINE else None
        return score, kind
    union = shingles[a] | shingles[b]
    score = len(shingles[a] & shingles[b]) / len(union) if union else 0.0
    return score, "duplicate" if score >= JACCARD else None


def _record(conn, key, kind, score) -> bool:
    """Write the relation row; False when a 'related' must not override an existing duplicate."""
    if kind == "duplicate":  # a duplicate supersedes a 'related' row for the same pair
        conn.execute("DELETE FROM relations WHERE item_a=? AND item_b=? AND type='related'", key)
    elif conn.execute("SELECT 1 FROM relations WHERE item_a=? AND item_b=? AND type='duplicate'",
                      key).fetchone():
        return False
    conn.execute("INSERT OR REPLACE INTO relations(item_a, item_b, type, score) VALUES (?,?,?,?)",
                 (*key, kind, score))
    return True


def _item_vectors(conn, services) -> dict:
    """item id -> unit vector for the active embedding model; empty without an embedder."""
    emb = services.registry.first("embed") if services is not None else None
    if emb is None:
        return {}
    ids, m = vectors.load(conn, _model_id(emb), "item")
    return dict(zip(ids, m))


def _other_items(a, rows, seen):
    """Yield (other_id, sorted_key) for unseen pairs of `a` with items of another source."""
    for b, rb in rows.items():
        if b == a or rb["source_id"] == rows[a]["source_id"]:
            continue
        key = tuple(sorted((a, b)))
        if key not in seen:
            seen.add(key)
            yield b, key


def find_near_duplicates(conn, item_ids, services,
                         threshold: float = DUPLICATE_COSINE) -> list[tuple[str, str, float]]:
    """Record duplicate/related relations for `item_ids` against all live items; -> new rows."""
    vecs = _item_vectors(conn, services)
    rows = {r["id"]: r for r in conn.execute(
        "SELECT id, title, body, source_id FROM knowledge_items WHERE deleted_at IS NULL")}
    sh, out = _ShingleCache(rows), []
    seen: set[tuple[str, str]] = set()
    for a in item_ids:
        if a not in rows:
            continue
        for b, key in _other_items(a, rows, seen):
            score, kind = _classify(a, b, vecs, sh, threshold)
            if kind and _record(conn, key, kind, score):
                out.append((*key, score))
    return out
