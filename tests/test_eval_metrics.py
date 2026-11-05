"""Unit tests for the evaluation harness helpers and dataset sanity (no model, no network)."""
import importlib.util
import json
import re
from pathlib import Path

import pytest

from infoparser.retrieval.search import STOPWORDS

EVAL = Path(__file__).parent.parent / "eval"


def _load(name):
    """Import eval/<name>.py by path (eval/ is not a package)."""
    spec = importlib.util.spec_from_file_location(name, EVAL / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


M = _load("metrics")


def _data(name):
    """Parsed eval/data/<name>.json."""
    return json.loads((EVAL / "data" / f"{name}.json").read_text(encoding="utf-8"))


def test_recall_at_k_counts_fraction_of_relevant_in_top_k():
    """Recall at k counts fraction of relevant in top k."""
    ranked = ["a", "b", "c", "d"]
    assert M.recall_at_k(ranked, {"c"}, 3) == 1.0
    assert M.recall_at_k(ranked, {"c"}, 2) == 0.0
    assert M.recall_at_k(ranked, {"a", "d"}, 3) == 0.5
    assert M.recall_at_k([], {"a"}, 5) == 0.0


def test_reciprocal_rank_first_relevant_or_zero():
    """Reciprocal rank first relevant or zero."""
    assert M.reciprocal_rank(["x", "a", "b"], {"a", "b"}) == 0.5
    assert M.reciprocal_rank(["x", "y"], {"a"}) == 0.0


def test_unique_keeps_first_occurrence_order():
    """Unique keeps first occurrence order."""
    assert M.unique(["a", "b", "a", "c", "b"]) == ["a", "b", "c"]


def test_wilson_interval_known_values_and_edges():
    """Wilson interval known values and edges."""
    lo, hi = M.wilson(8, 10)
    assert lo == pytest.approx(0.4902, abs=1e-3) and hi == pytest.approx(0.9433, abs=1e-3)
    lo, hi = M.wilson(0, 10)
    assert lo == 0.0 and 0.2 < hi < 0.35
    lo, hi = M.wilson(10, 10)
    assert hi == 1.0 and lo > 0.65
    assert M.wilson(0, 0) == (0.0, 1.0)


def test_bootstrap_ci_is_deterministic_and_brackets_mean():
    """Bootstrap ci is deterministic and brackets mean."""
    vals = [0.0, 1.0, 1.0, 0.5, 0.25, 1.0, 0.0, 0.75]
    a, b = M.bootstrap_ci(vals, seed=3), M.bootstrap_ci(vals, seed=3)
    assert a == b
    assert a[0] <= sum(vals) / len(vals) <= a[1]
    assert M.bootstrap_ci([0.5], seed=1) == (0.5, 0.5)
    assert M.bootstrap_ci([], seed=1) == (0.0, 0.0)


def test_fact_matching_rule_exact_and_loose():
    """Fact matching rule exact and loose."""
    items = ["Weekly active users reached 48,200 in March", "Launch moved to 16 April"]
    assert M.fact_found("48,200", items)
    assert M.fact_found("WEEKLY ACTIVE   users", items)  # case and whitespace insensitive
    assert not M.fact_found("16 May", items)
    # exact is substring within ONE item; words split across items do not count
    assert not M.fact_found("48,200 launch", items)
    # loose: every token present in one item, any order, punctuation ignored
    assert M.fact_found("april 16", items, loose=True)
    assert not M.fact_found("april 16", items)
    assert not M.fact_found("april 17", items, loose=True)
    assert not M.fact_found("anything", [])


def test_summarize_min_median_max():
    """Summarize min median max."""
    assert M.summarize([0.4, 0.9, 0.5]) == {"n": 3, "min": 0.4, "median": 0.5, "max": 0.9}
    assert M.summarize([])["n"] == 0


def test_threshold_precision_recall():
    """Threshold precision recall."""
    scores = [0.95, 0.93, 0.90, 0.80, 0.50]
    pos = [True, True, False, True, False]
    p, r = M.precision_recall(scores, pos, 0.92)
    assert (p, r) == (1.0, pytest.approx(2 / 3))
    p, r = M.precision_recall(scores, pos, 0.99)
    assert p is None and r == 0.0
    p, r = M.precision_recall(scores, pos, 0.0)
    assert (p, r) == (pytest.approx(0.6), 1.0)


def test_band_precision_recall_for_related_band():
    """Band precision recall for related band."""
    scores = [0.95, 0.80, 0.76, 0.60, 0.74]
    pos = [False, True, True, False, True]
    p, r = M.precision_recall(scores, pos, 0.75, upper=0.92)
    assert (p, r) == (1.0, pytest.approx(2 / 3))


def test_dataset_sizes_meet_plan_minimums():
    """Dataset sizes meet plan minimums."""
    ret = _data("retrieval")
    assert len(ret["docs"]) >= 60 and len({d[0].split("-")[0] for d in ret["docs"]}) >= 6
    assert len(ret["queries"]) >= 60
    assert {q["category"] for q in ret["queries"]} == {"keyword", "entity", "numeric", "paraphrase"}
    ids = {d[0] for d in ret["docs"]}
    assert len(ids) == len(ret["docs"])
    assert all(q["relevant"] and set(q["relevant"]) <= ids for q in ret["queries"])
    pairs = _data("dedupe")
    for label in ("duplicate", "related", "unrelated"):
        assert sum(p["label"] == label for p in pairs) >= 40
    ext = _data("extraction")
    assert len(ext) >= 12 and all(len(e["facts"]) >= 4 for e in ext)


def test_every_required_fact_is_in_its_source_text():
    """Every required fact is in its source text."""
    for e in _data("extraction"):
        for f in e["facts"]:
            assert M.fact_found(f, [e["text"]]), (e["id"], f)


def _content(text):
    """Lower-cased non-stopword tokens (what FTS can match on)."""
    return {t.lower() for t in re.findall(r"\w+", text)} - STOPWORDS


def test_paraphrase_queries_share_no_content_word_with_relevant_docs():
    """Paraphrase queries share no content word with relevant docs."""
    ret = _data("retrieval")
    docs = dict(ret["docs"])
    for q in (q for q in ret["queries"] if q["category"] == "paraphrase"):
        for rel in q["relevant"]:
            assert not _content(q["q"]) & _content(docs[rel]), (q["q"], rel)
