import pytest

from infoparser.pipeline import runner
from infoparser.retrieval.search import search


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


@pytest.mark.parametrize("q", ['"foo" AND ( NEAR', "NEAR(", '"', "a OR", "col:x *", "-", "'; DROP"])
def test_search_query_with_fts_special_chars_does_not_crash(loaded, q):
    assert isinstance(search(loaded, q), list)
