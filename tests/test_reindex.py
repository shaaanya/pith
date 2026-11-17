from stubs.hash_embedder import HashEmbedder
from pith.pipeline import runner
from pith.retrieval import index, vectors
from pith.retrieval.search import search

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
    from pith.worker import Processed
    iid = svc.inbox.submit(adapter="t", text=TEXT).id
    assert isinstance(runner.process(svc, iid), Processed)
    ev = svc.conn.execute("SELECT status, detail FROM processing_events WHERE inbox_id=? AND stage='embed'",
                          (iid,)).fetchone()
    assert ev["status"] == "error" and "embedder down" in ev["detail"]


def test_openai_compat_embeddings(svc, tmp_path):
    from stubs.openai_stub import OpenAIStub
    from pith.providers.openai_compat import OpenAICompatBackend
    with OpenAIStub() as stub:
        svc.registry.first = lambda t, b=OpenAICompatBackend("oa", stub.base_url, "m", embed_model="e"): \
            b if t == "embed" else None
        runner.process(svc, svc.inbox.submit(adapter="t", text=TEXT).id)
    assert list(models(svc)) == ["oa:e"]


def test_reindex_failure_midway_keeps_old_vectors(svc, use_embedder):
    use_embedder(svc, HashEmbedder("m1"))
    runner.process(svc, svc.inbox.submit(adapter="t", text=TEXT).id)
    before = models(svc)

    class Flaky(HashEmbedder):
        calls = 0

        def embed(self, texts):
            Flaky.calls += 1
            if Flaky.calls > 1:
                raise RuntimeError("down")
            return super().embed(texts)
    use_embedder(svc, Flaky("m1"))
    import pytest
    with pytest.raises(RuntimeError):
        index.reindex(svc, prune_old=True)
    assert models(svc) == before


def test_model_id_probe_cached_and_empty_texts_skipped(svc, use_embedder):
    class Counting(HashEmbedder):
        texts = []

        def embed(self, texts):
            Counting.texts.append(list(texts))
            return super().embed(texts)
    use_embedder(svc, Counting())
    svc.conn.execute("INSERT INTO sources(id) VALUES ('s')")
    svc.conn.execute("INSERT INTO segments(source_id, idx, text) VALUES ('s', 0, '   ')")
    svc.conn.execute("INSERT INTO segments(source_id, idx, text) VALUES ('s', 1, 'real text')")
    index.embed_pending(svc)
    index.embed_pending(svc)
    probes = [t for t in Counting.texts if t == ["."]]
    assert len(probes) == 1
    assert not any("   " in t for t in Counting.texts)
    assert models(svc) == {"test-embed-1": 1}


def test_cli_reindex(svc, use_embedder, monkeypatch, capsys):
    from pith import cli
    use_embedder(svc, HashEmbedder("m1"))
    runner.process(svc, svc.inbox.submit(adapter="t", text=TEXT).id)
    use_embedder(svc, HashEmbedder("m2"))
    monkeypatch.setattr(cli, "_services", lambda a: svc)
    cli.main(["reindex"])
    assert "reindexed" in capsys.readouterr().out and set(models(svc)) == {"m1", "m2"}
    cli.main(["reindex", "--prune-old"])
    assert set(models(svc)) == {"m2"}
