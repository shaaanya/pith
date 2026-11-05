from infoparser.domain.models import Candidate
from infoparser.pipeline import entities
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

