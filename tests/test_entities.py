from infoparser.domain.models import Candidate
from infoparser.pipeline import entities, runner
from infoparser.retrieval.search import search
from infoparser.store import knowledge
from infoparser.store.knowledge import get_item


def mk(svc, cands):
    sid = knowledge.save_source(svc.conn, url=None, title="t", author=None, platform=None, content_type="note",
                                blob_sha256=None, text_sha256="x", extractor="note")
    ids = knowledge.save_items(svc.conn, sid, cands, "test", [])
    return ids


def test_entities_merge_case_insensitive(svc):
    cands = [Candidate("insight", "a", "alpha body", entities=["OpenAI", " openai "], topics=["RAG", "rag "]),
             Candidate("insight", "b", "beta body", entities=["OPENAI", "Qdrant"], topics=["Rag"])]
    ids = mk(svc, cands)
    entities.apply(svc.conn, ids, cands)
    assert svc.conn.execute("SELECT count(*) FROM entities").fetchone()[0] == 2
    assert svc.conn.execute("SELECT count(*) FROM topics").fetchone()[0] == 1
    assert svc.conn.execute("SELECT count(*) FROM item_entities").fetchone()[0] == 3
    assert svc.conn.execute("SELECT count(*) FROM item_topics").fetchone()[0] == 2
    entities.apply(svc.conn, ids, cands)  # idempotent
    assert svc.conn.execute("SELECT count(*) FROM item_topics").fetchone()[0] == 2


def test_tables_are_single_source_of_truth(svc):
    cands = [Candidate("insight", "a", "alpha", entities=["X"], topics=["T"])]
    ids = mk(svc, cands)
    d = get_item(svc.conn, ids[0])["data"]
    assert "entities" not in d and "topics" not in d


def test_search_topic_filter(svc):
    cands = [Candidate("insight", "a", "zebra alpha", topics=["Animals"]),
             Candidate("insight", "b", "zebra beta", topics=["Cars"])]
    ids = mk(svc, cands)
    entities.apply(svc.conn, ids, cands)
    hits = search(svc, "zebra", filters={"topic": " animals "})
    assert [h.item_id for h in hits] == [ids[0]]
    assert len(search(svc, "zebra")) == 2



def test_apply_skips_malformed_members(svc):
    cands = [Candidate("insight", "a", "alpha", entities=[None, 5, {"x": 1}, "Ok"], topics="abc"),
             Candidate("insight", "b", "beta", entities=123, topics=[None, ["n"], " T "])]
    ids = mk(svc, cands)
    entities.apply(svc.conn, ids, cands)
    assert [r[0] for r in svc.conn.execute("SELECT name FROM entities")] == ["ok"]
    assert [r[0] for r in svc.conn.execute("SELECT name FROM topics")] == ["t"]


def _runner_with(monkeypatch, cands):
    monkeypatch.setattr(runner, "distill", lambda *a, **k: (cands, "test"))


def test_malformed_entities_do_not_fail_item(svc, monkeypatch):
    from infoparser.worker import Processed
    _runner_with(monkeypatch, [Candidate("insight", "a", "alpha body text", entities=123, topics=[None])])
    iid = svc.inbox.submit(adapter="t", text="alpha body text here").id
    assert isinstance(runner.process(svc, iid), Processed)
    assert svc.conn.execute("SELECT count(*) FROM knowledge_items").fetchone()[0] == 1


def test_entities_apply_crash_is_contained(svc, monkeypatch):
    from infoparser.worker import Processed
    _runner_with(monkeypatch, [Candidate("insight", "a", "alpha body text")])
    monkeypatch.setattr(entities, "apply", lambda *a: 1 / 0)
    iid = svc.inbox.submit(adapter="t", text="alpha body text here").id
    assert isinstance(runner.process(svc, iid), Processed)
    assert svc.conn.execute("SELECT count(*) FROM knowledge_items").fetchone()[0] == 1
    ev = svc.conn.execute("SELECT status, detail FROM processing_events WHERE inbox_id=? AND stage='entities'",
                          (iid,)).fetchone()
    assert ev["status"] == "error" and "ZeroDivisionError" in ev["detail"]


def test_event_log_failure_in_enrichment_does_not_fail_item(svc, monkeypatch, use_embedder):
    from infoparser.worker import Processed
    from infoparser.pipeline import dedupe
    monkeypatch.setattr(dedupe, "find_near_duplicates", lambda *a, **k: 1 / 0)
    real = runner._stage

    def flaky(conn, iid, stage, t0, detail="", model=None, level="info"):
        if level == "error":
            raise RuntimeError("event log down")
        return real(conn, iid, stage, t0, detail, model, level)
    monkeypatch.setattr(runner, "_stage", flaky)
    iid = svc.inbox.submit(adapter="t", text="alpha body text here").id
    assert isinstance(runner.process(svc, iid), Processed)


def count_for(svc, ids):
    q = ",".join("?" * len(ids))
    c = svc.conn
    return {
        "topics": c.execute(f"SELECT count(*) FROM item_topics WHERE item_id IN ({q})", ids).fetchone()[0],
        "entities": c.execute(f"SELECT count(*) FROM item_entities WHERE item_id IN ({q})", ids).fetchone()[0],
        "relations": c.execute(f"SELECT count(*) FROM relations WHERE item_a IN ({q}) OR item_b IN ({q})",
                               ids + ids).fetchone()[0],
        "embeddings": c.execute(f"SELECT count(*) FROM embeddings WHERE owner_type='item' AND owner_id IN ({q})",
                                ids).fetchone()[0],
    }


def test_reprocess_purges_links_of_replaced_items_keeps_user_edited(svc):
    from infoparser.retrieval import vectors
    cands = [Candidate("insight", "a", "alpha", entities=["E"], topics=["T"]),
             Candidate("insight", "b", "beta", entities=["E"], topics=["T"])]
    sid = knowledge.save_source(svc.conn, url=None, title="t", author=None, platform=None, content_type="note",
                                blob_sha256=None, text_sha256="x", extractor="note")
    other = knowledge.save_source(svc.conn, url=None, title="o", author=None, platform=None, content_type="note",
                                  blob_sha256=None, text_sha256="y", extractor="note")
    a, b = knowledge.save_items(svc.conn, sid, cands, "t", [])
    [o] = knowledge.save_items(svc.conn, other, [Candidate("insight", "o", "omega")], "t", [])
    entities.apply(svc.conn, [a, b], cands)
    for i in (a, b):
        vectors.put(svc.conn, "item", [i], "m", [[1, 0]])
        svc.conn.execute("INSERT INTO relations VALUES (?,?,?,?)", (i, o, "related", 0.8))
    knowledge.update_item(svc.conn, b, title="edited")  # user_edited -> preserved on reprocess
    assert vectors.cosine_topk(svc.conn, "m", [1, 0], 5, owner_type="item")  # b's vector refreshed away by edit
    knowledge.save_items(svc.conn, sid, [Candidate("insight", "n", "new")], "t", [])
    assert count_for(svc, [a]) == {"topics": 0, "entities": 0, "relations": 0, "embeddings": 0}
    kept = count_for(svc, [b])
    assert kept["topics"] == 1 and kept["entities"] == 1 and kept["relations"] == 1
    knowledge.delete_item(svc.conn, b)
    assert count_for(svc, [b]) == {"topics": 0, "entities": 0, "relations": 0, "embeddings": 0}


def test_update_item_invalidates_embedding(svc):
    from infoparser.retrieval import vectors
    ids = mk(svc, [Candidate("insight", "a", "alpha")])
    vectors.put(svc.conn, "item", ids, "m", [[1, 0]])
    knowledge.update_item(svc.conn, ids[0], body="changed")
    assert vectors.cosine_topk(svc.conn, "m", [1, 0], 5, owner_type="item") == []


def test_cosine_topk_excludes_soft_deleted_items(svc):
    from infoparser.retrieval import vectors
    ids = mk(svc, [Candidate("insight", "a", "alpha")])
    vectors.put(svc.conn, "item", ids, "m", [[1, 0]])
    svc.conn.execute("UPDATE knowledge_items SET deleted_at='x'")
    assert vectors.cosine_topk(svc.conn, "m", [1, 0], 5, owner_type="item") == []


def test_normalize_lives_in_domain():
    from infoparser.domain.text import normalize
    assert normalize("  Open   AI ") == "open ai"
