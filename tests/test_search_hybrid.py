import pytest

from infoparser.pipeline import runner
from infoparser.retrieval import search as S
from infoparser.retrieval.search import search, search_ex
from stubs.concept_embedder import ConceptEmbedder
from stubs.hash_embedder import HashEmbedder

NASH = "Firms in an oligopoly reach a Nash equilibrium when no firm gains by changing its price alone."
BREAD = "Sourdough bread needs a patient starter and a long fermentation."


def load(svc, *texts, ctx=None):
    for t in texts:
        runner.process(svc, svc.inbox.submit(adapter="t", text=t, user_context=ctx).id)


def titles(hits):
    return [h.text.lower() for h in hits]


def test_hybrid_beats_fts_on_paraphrase_query(svc, use_embedder):
    use_embedder(svc, ConceptEmbedder())
    load(svc, NASH, BREAD)
    q = "game theory and pricing"
    assert not [h for h in search(svc, q, mode="fts") if "nash" in h.text.lower()]
    r = search_ex(svc, q)
    assert r.mode == "hybrid" and r.hits and "nash" in r.hits[0].text.lower()
    assert "nash" not in q


def test_no_embedder_is_fts_mode_without_warning(svc):
    load(svc, NASH)
    r = search_ex(svc, "oligopoly")
    assert r.mode == "fts" and r.hits and r.warnings == []


def test_embedder_failure_degrades_to_fts_with_warning(svc, use_embedder):
    class Boom(ConceptEmbedder):
        def embed(self, texts):
            if self.armed:
                raise RuntimeError("embedder down")
            return super().embed(texts)
        armed = False
    emb = use_embedder(svc, Boom())
    load(svc, NASH)
    emb.armed = True
    r = search_ex(svc, "oligopoly")
    assert r.mode == "fts" and r.hits and "vector search unavailable" in r.warnings[0]


def test_unindexed_model_warns_and_uses_fts(svc, use_embedder):
    use_embedder(svc, HashEmbedder("m1"))
    load(svc, NASH)
    use_embedder(svc, HashEmbedder("m2"))
    r = search_ex(svc, "oligopoly")
    assert r.mode == "fts" and r.hits and "reindex" in r.warnings[0]


def test_per_source_cap_keeps_one_long_source_from_filling_topk(svc):
    load(svc, " ".join(f"Oligopoly pricing sentence number {i} about firms." for i in range(30)),
         "A second source mentions oligopoly once in passing.")
    hits = search(svc, "oligopoly", limit=10)
    per = {}
    for h in hits:
        per[h.source_id] = per.get(h.source_id, 0) + 1
    assert max(per.values()) <= 2 and len(per) == 2
    assert max(search_ex(svc, "oligopoly", limit=10, per_source=1).hits.__len__() for _ in [0]) == 2


def test_rrf_constant_and_candidate_bounds():
    assert S.RRF_K == 60 and S.CANDIDATES == 50 and S.RERANK_TOP == 20 and S.PER_SOURCE_CAP == 2


class Reranker:
    locality = "local"
    name = "rr"
    capabilities = type("C", (), {"rerank": True})()

    def __init__(self):
        self.seen = None

    def rerank(self, query, docs):
        self.seen = docs
        return [1.0 if "bread" in d.lower() else 0.0 for d in docs]


def test_rerank_used_when_configured_and_skipped_otherwise(svc, use_embedder):
    load(svc, NASH + " Prices matter.", BREAD + " Prices matter.")
    base = [h.item_id for h in search(svc, "prices")]
    rr = Reranker()
    orig = svc.registry.first
    svc.registry.first = lambda t: rr if t == "rerank" else orig(t)
    hits = search(svc, "prices")
    assert rr.seen and "bread" in hits[0].text.lower()
    assert [h.item_id for h in hits][0] != base[0] or "bread" in titles(hits[:1])[0]
    rr.rerank = lambda q, d: (_ for _ in ()).throw(RuntimeError("x"))
    r = search_ex(svc, "prices")
    assert r.hits and "rerank skipped" in r.warnings[0]


def test_remote_reranker_recorded_as_egress(svc):
    load(svc, NASH)
    rr = Reranker()
    rr.locality, rr.name = "remote", "cloudrank"
    orig = svc.registry.first
    svc.registry.first = lambda t: rr if t == "rerank" else orig(t)
    assert search_ex(svc, "oligopoly").egress == ["cloudrank"]


def test_filters_by_topic_and_provenance(svc):
    load(svc, "Rust ownership prevents data races at compile time. Rust borrowing is checked.")
    load(svc, "Sourdough starter feeding schedule matters. The starter likes flour.")
    svc.conn.execute("INSERT INTO topics(id,name) VALUES ('t1','baking')")
    ids = {r[0] for r in svc.conn.execute("SELECT id FROM knowledge_items WHERE body LIKE '%starter%'")}
    for iid in ids:
        svc.conn.execute("INSERT INTO item_topics VALUES (?, 't1')", (iid,))
    assert {h.item_id for h in search_ex(svc, "starter", filters={"topic": "Baking"}, per_source=99).hits} == ids
    assert search(svc, "rust", filters={"topic": "baking"}) == []
    allh = {h.item_id for h in search_ex(svc, "starter", per_source=99).hits}
    by = {p: {h.item_id for h in search_ex(svc, "starter", filters={"provenance": p}, per_source=99).hits} for p in ("stated", "inferred")}
    assert by["stated"] | by["inferred"] == allh and not by["stated"] & by["inferred"]
    assert search(svc, "starter", filters={"provenance": "external"}) == []
    assert search(svc, "starter", filters={"since": "2999-01-01T00:00:00Z"}) == []
    assert search(svc, "starter", filters={"since": "2000-01-01T00:00:00Z"})


def test_soft_deleted_items_never_returned(svc, use_embedder):
    use_embedder(svc, ConceptEmbedder())
    load(svc, NASH)
    from infoparser.store.knowledge import delete_item
    for r in svc.conn.execute("SELECT id FROM knowledge_items").fetchall():
        delete_item(svc.conn, r[0])
    assert [h for h in search(svc, "game theory pricing") if h.item_id] == []


def _many(svc, n, platform=None, extra=""):
    for i in range(n):
        svc.inbox.submit(adapter="t", text=f"Oligopoly equilibrium note {i}. {extra}", platform=platform)


def test_vector_prefilter_narrow_platform_still_yields_hits(svc, use_embedder, drain):
    use_embedder(svc, ConceptEmbedder())
    _many(svc, 70)
    svc.inbox.submit(adapter="t", text="Oligopoly equilibrium outlier with many unrelated words here "
                     "alpha beta gamma delta epsilon zeta eta theta iota kappa", platform="special")
    drain(svc)
    assert svc.conn.execute("SELECT count(*) FROM sources WHERE platform='special'").fetchone()[0] == 1
    r = search_ex(svc, "game theory strategic rivals", filters={"platform": "special"})
    assert r.mode == "hybrid" and r.hits and all(h.platform == "special" for h in r.hits)


def test_egress_recorded_before_remote_call_even_on_failure(svc, use_embedder):
    class Remote(ConceptEmbedder):
        locality = "remote"

        def embed(self, texts):
            raise RuntimeError("net down")
    use_embedder(svc, Remote(name="cloudembed"))
    load(svc, NASH)
    r = search_ex(svc, "oligopoly")
    assert r.egress == ["cloudembed"] and r.warnings
    rr = Reranker()
    rr.locality, rr.name = "remote", "cloudrank"
    rr.rerank = lambda q, d: (_ for _ in ()).throw(RuntimeError("x"))
    use_embedder(svc, None)
    orig = svc.registry.first
    svc.registry.first = lambda t: rr if t == "rerank" else orig(t)
    assert search_ex(svc, "oligopoly").egress == ["cloudrank"]


def test_since_applies_to_segments_and_items_alike(svc):
    load(svc, "Alpha beta gamma delta one. Alpha beta gamma delta two. Alpha beta gamma delta three. "
              "Alpha beta gamma delta four. Alpha beta gamma delta five. Alpha beta gamma delta six. "
              "Alpha beta gamma delta seven. Trailing remark about zebrafish only.")
    assert search(svc, "zebrafish", filters={"since": "2000-01-01T00:00:00Z"})
    assert search(svc, "zebrafish", filters={"since": "2999-01-01T00:00:00Z"}) == []


def test_segments_of_fully_deleted_source_not_returned(svc):
    from infoparser.store.knowledge import delete_item
    load(svc, "Alpha beta gamma delta one. Alpha beta gamma delta two. Alpha beta gamma delta three. "
              "Alpha beta gamma delta four. Alpha beta gamma delta five. Alpha beta gamma delta six. "
              "Alpha beta gamma delta seven. Trailing remark about zebrafish only.")
    assert search(svc, "zebrafish")
    for r in svc.conn.execute("SELECT id FROM knowledge_items").fetchall():
        delete_item(svc.conn, r[0])
    assert search(svc, "zebrafish") == []
    assert search(svc, "zebrafish", mode="fts") == []
