from stubs.hash_embedder import HashEmbedder
from infoparser.pipeline import runner
from infoparser.retrieval import index, vectors
from infoparser.retrieval.search import search

TEXT = "Retrieval augmented generation combines search with generation.\n\nChunking strategy matters a lot."


def models(svc):
    return {r[0]: r[1] for r in svc.conn.execute("SELECT model_id, count(*) FROM embeddings GROUP BY model_id")}


def test_switch_embedding_model_reindex_rebuilds_and_old_ignored(svc, use_embedder):
    use_embedder(svc, HashEmbedder("m1"))
    runner.process(svc, svc.inbox.submit(adapter="t", text=TEXT).id)
    assert set(models(svc)) == {"m1"}  # runner embedded after save
    use_embedder(svc, HashEmbedder("m2"))
    q = HashEmbedder("m2").embed(["retrieval search"]).vectors[0]
    assert vectors.cosine_topk(svc.conn, "m2", q, 5) == []  # old vectors ignored
    assert index.embed_pending(svc) > 0 and set(models(svc)) == {"m1", "m2"}
    n = index.reindex(svc)
    assert n > 0 and set(models(svc)) == {"m1", "m2"} and models(svc)["m2"] == n
    assert vectors.cosine_topk(svc.conn, "m2", q, 5)
    index.reindex(svc, prune_old=True)
    assert set(models(svc)) == {"m2"}


def test_search_still_works_after_embedder_removed(svc, use_embedder):
    use_embedder(svc)
    runner.process(svc, svc.inbox.submit(adapter="t", text=TEXT).id)
    assert models(svc)
    use_embedder(svc, None)
    assert index.embed_pending(svc) == 0 and index.reindex(svc, prune_old=True) == 0
    assert models(svc)  # nothing pruned without an active embedder
    assert search(svc, "chunking")


def test_embed_failure_never_fails_item(svc, use_embedder):
    class Boom(HashEmbedder):
        def embed(self, texts):
            raise RuntimeError("embedder down")
    use_embedder(svc, Boom())
    from infoparser.worker import Processed
    iid = svc.inbox.submit(adapter="t", text=TEXT).id
    assert isinstance(runner.process(svc, iid), Processed)
    ev = svc.conn.execute("SELECT status, detail FROM processing_events WHERE inbox_id=? AND stage='embed'",
                          (iid,)).fetchone()
    assert ev["status"] == "error" and "embedder down" in ev["detail"]


def test_openai_compat_embeddings(svc, tmp_path):
    from stubs.openai_stub import OpenAIStub
    from infoparser.providers.openai_compat import OpenAICompatBackend
    with OpenAIStub() as stub:
        svc.registry.first = lambda t, b=OpenAICompatBackend("oa", stub.base_url, "m", embed_model="e"): \
            b if t == "embed" else None
        runner.process(svc, svc.inbox.submit(adapter="t", text=TEXT).id)
    assert list(models(svc)) == ["oa:e"]
