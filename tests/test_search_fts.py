import sqlite3

import pytest

from infoparser.pipeline import runner
from infoparser.retrieval.search import fts_query, search

# more than 5 sentences so heuristic distill (top 5) leaves "zebrafish" only in the raw segment
RAW = ("Embeddings power semantic retrieval systems. " + "Filler sentence number one is here. " * 0 +
       "Alpha beta gamma delta one. Alpha beta gamma delta two. Alpha beta gamma delta three. "
       "Alpha beta gamma delta four. Alpha beta gamma delta five. Alpha beta gamma delta six. "
       "Alpha beta gamma delta seven. Trailing remark about zebrafish only.")


@pytest.fixture
def loaded(svc):
    iid = svc.inbox.submit(adapter="t", text="Embeddings power semantic retrieval systems.\n\nVector databases store them.").id
    runner.process(svc, iid)
    return svc


def test_search_fts_finds_by_word_and_prefix(loaded):
    hits = search(loaded, "semantic")
    assert hits and hits[0].item_id and hits[0].provenance in ("stated", "inferred", "external")
    assert search(loaded, "retriev")  # prefix on last term
    assert search(loaded, "zzzznotthere") == []
    assert search(loaded, "", limit=5) == []
    assert search(loaded, "semantic", filters={"kind": "no-such-kind"}) == []


@pytest.mark.parametrize("q", ['semantic AND ( NEAR', '"semantic"', "NEAR(semantic", "col:semantic *",
                               "'; semantic", "semantic OR"])
def test_special_chars_still_find_item(loaded, q):
    assert search(loaded, q), q


@pytest.mark.parametrize("q", ['"', "(", "", "   ", "-", "NEAR(", '"foo" AND ( NEAR'])
def test_degenerate_queries_return_empty(loaded, q):
    assert search(loaded, q) == []


def test_sanitiser_is_necessary(loaded):
    with pytest.raises(sqlite3.OperationalError):
        loaded.conn.execute("SELECT 1 FROM items_fts WHERE items_fts MATCH ?", ('semantic AND ( NEAR',)).fetchall()
    assert fts_query('semantic AND ( NEAR') == '"semantic" OR "AND" OR "NEAR"*'


def test_segment_hit_for_word_only_in_raw_text(svc):
    iid = svc.inbox.submit(adapter="t", text=RAW).id
    runner.process(svc, iid)
    live = svc.conn.execute("SELECT title, body FROM knowledge_items WHERE deleted_at IS NULL").fetchall()
    assert not any("zebrafish" in (r["title"] + r["body"]).lower() for r in live)
    hits = search(svc, "zebrafish")
    assert len(hits) == 1
    h = hits[0]
    assert h.kind == "segment" and h.item_id is None and h.segment_id and h.source_id
    assert h.locator.startswith("char=") and "zebrafish" in h.snippet.lower()


def test_segment_hits_dedupe_per_source_and_after_items(svc):
    iid = svc.inbox.submit(adapter="t", text="Alpha marker one.\n\n" + "Alpha marker two.\n\n" * 1).id
    runner.process(svc, iid)
    hits = search(svc, "alpha")
    assert sum(1 for h in hits if h.kind != "segment") >= 1
    # source already represented by an item hit -> no segment hit for it
    assert not any(h.kind == "segment" for h in hits)
    j = svc.inbox.submit(adapter="t", text=RAW).id
    runner.process(svc, j)
    hits = search(svc, "alpha")
    segs = [h for h in hits if h.kind == "segment"]
    assert len(segs) <= 1 and [h.kind == "segment" for h in hits] == sorted(h.kind == "segment" for h in hits)


def test_filter_excludes_segment_hits(svc):
    iid = svc.inbox.submit(adapter="t", text=RAW).id
    runner.process(svc, iid)
    assert search(svc, "zebrafish")
    assert search(svc, "zebrafish", filters={"kind": "insight"}) == []
    assert search(svc, "zebrafish", filters={"provenance": "stated"}) == []
