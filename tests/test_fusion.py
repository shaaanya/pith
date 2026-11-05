"""Reciprocal rank fusion."""
from infoparser.retrieval.fusion import RRF_K, rrf


def test_rrf_ordering():
    """Fusion order, scores and de-duplication within a list."""
    out = rrf([["a", "b", "c"], ["c", "b", "d"]], k=60)
    keys = [k for k, _ in out]
    assert keys[:2] == ["c", "b"] and set(keys) == {"a", "b", "c", "d"}
    assert dict(out)["b"] == 2 / 62
    assert RRF_K == 60 and not rrf([])
    assert rrf([["x", "x"]]) == [("x", 1 / 61)]  # duplicates within a list count once
