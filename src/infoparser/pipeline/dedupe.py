"""Near-duplicate / related detection, writing `relations`. Never raises for lack of an embedder.
Duplicates: cosine >= threshold when both items have vectors for the active model, else shingle Jaccard >= 0.8
over title+body. Related (embeddings only): RELATED <= cosine < threshold. Items of the same source are skipped.
ponytail: compares each new item against all live items (O(N)); add an ANN/LSH shortlist if N gets large."""
import re

from infoparser.retrieval import vectors

JACCARD = 0.8
RELATED = 0.75
_SHINGLE = 3


def _shingles(text: str) -> set:
    w = re.findall(r"\w+", (text or "").lower())
    return {tuple(w[i:i + _SHINGLE]) for i in range(max(1, len(w) - _SHINGLE + 1))} if w else set()


def find_near_duplicates(conn, item_ids, services, threshold: float = 0.92) -> list[tuple[str, str, float]]:
    emb = services.registry.first("embed") if services is not None else None
    vecs: dict[str, object] = {}
    if emb is not None:
        mid = emb.embed(["."]).model_id
        ids, m = vectors.load(conn, mid, "item")
        vecs = dict(zip(ids, m))
    rows = {r["id"]: r for r in conn.execute(
        "SELECT id, title, body, source_id FROM knowledge_items WHERE deleted_at IS NULL")}
    sh: dict[str, set] = {}
    out, seen = [], set()
    for a in item_ids:
        ra = rows.get(a)
        if ra is None:
            continue
        for b, rb in rows.items():
            if b == a or rb["source_id"] == ra["source_id"]:
                continue
            key = tuple(sorted((a, b)))
            if key in seen:
                continue
            seen.add(key)
            if a in vecs and b in vecs:
                score = float(vecs[a] @ vecs[b])
                kind = "duplicate" if score >= threshold else "related" if score >= RELATED else None
            else:
                for x in (a, b):
                    sh.setdefault(x, _shingles(f"{rows[x]['title']} {rows[x]['body']}"))
                u = sh[a] | sh[b]
                score = len(sh[a] & sh[b]) / len(u) if u else 0.0
                kind = "duplicate" if score >= JACCARD else None
            if kind:
                conn.execute("INSERT OR REPLACE INTO relations(item_a, item_b, type, score) VALUES (?,?,?,?)",
                             (*key, kind, score))
                out.append((*key, score))
    return out
