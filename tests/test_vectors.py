"""Vector store: cosine top-k and pending embeds."""
from pith.retrieval import index, vectors


def test_cosine_topk_filters_by_model_id(svc):
    """Top-k filters by model id, owner type and dimension."""
    vectors.put(svc.conn, "segment", ["a", "b"], "m1", [[1, 0], [0, 1]])
    vectors.put(svc.conn, "segment", ["c"], "m2", [[1, 0]])
    svc.conn.execute("INSERT INTO knowledge_items(id,kind,provenance,created_at,updated_at)"
                     " VALUES ('i','insight','inferred','x','x')")
    vectors.put(svc.conn, "item", ["i"], "m1", [[1, 0]])
    got = vectors.cosine_topk(svc.conn, "m1", [1, 0.1], 5)
    assert [o for o, _ in got] == ["a", "b"] and got[0][1] > got[1][1]
    assert [o for o, _ in vectors.cosine_topk(svc.conn, "m2", [1, 0], 5)] == ["c"]
    assert vectors.cosine_topk(svc.conn, "m1", [1, 0], 5, owner_type="item")[0][0] == "i"
    assert not vectors.cosine_topk(svc.conn, "nope", [1, 0], 5)
    # dim mismatch ignored
    assert not vectors.cosine_topk(svc.conn, "m1", [1, 0, 0], 5)


def test_embed_pending_noop_without_embedder(svc):
    """With no embedder, nothing is embedded."""
    svc.inbox.submit(adapter="t", text="hello world note")
    assert index.embed_pending(svc) == 0
