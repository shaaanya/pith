"""float32 BLOB vectors, normalized at write time, brute-force cosine (numpy). Rows are keyed by model_id;
queries only ever see rows of the model they ask for.
ponytail: brute force is fine to ~100k vectors; swap for an ANN index beyond that."""
import numpy as np

from infoparser.ids import utcnow
from infoparser.store.db import transaction


def _unit(v) -> np.ndarray:
    a = np.asarray(v, dtype=np.float32)
    n = float(np.linalg.norm(a))
    return a / n if n else a


def put(conn, owner_type: str, owner_ids: list, model_id: str, vecs) -> None:
    now = utcnow()
    with transaction(conn):
        for oid, v in zip(owner_ids, vecs):
            a = _unit(v)
            conn.execute("INSERT OR REPLACE INTO embeddings(owner_type, owner_id, model_id, dim, vector, created_at)"
                         " VALUES (?,?,?,?,?,?)", (owner_type, str(oid), model_id, len(a), a.tobytes(), now))


def load(conn, model_id: str, owner_type: str = "segment", dim: int | None = None):
    rows = conn.execute("SELECT owner_id, dim, vector FROM embeddings WHERE owner_type=? AND model_id=?",
                        (owner_type, model_id)).fetchall()
    if dim is not None:
        rows = [r for r in rows if r["dim"] == dim]
    elif rows:
        rows = [r for r in rows if r["dim"] == rows[0]["dim"]]
    if not rows:
        return [], np.zeros((0, 0), dtype=np.float32)
    return [r["owner_id"] for r in rows], np.vstack([np.frombuffer(r["vector"], dtype=np.float32) for r in rows])


def cosine_topk(conn, model_id: str, query_vec, k: int, owner_type: str = "segment") -> list[tuple[str, float]]:
    q = _unit(query_vec)
    ids, m = load(conn, model_id, owner_type, dim=len(q))
    if not ids:
        return []
    scores = m @ q
    top = np.argsort(-scores)[:k]
    return [(ids[i], float(scores[i])) for i in top]
