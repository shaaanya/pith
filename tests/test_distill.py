import json

import pytest

from infoparser.config import Config
from infoparser.domain.models import SegmentIn
from infoparser.pipeline.distill import distill
from infoparser.pipeline.schemas import SCHEMAS, profile_for
from infoparser.providers.heuristic import HeuristicBackend
from infoparser.providers.ports import Capabilities, GenResult, ProviderError
from infoparser.providers.registry import Registry

TEXT = ("Rust ownership prevents data races at compile time. Borrowing lets code read without owning. "
        "Lifetimes describe how long references stay valid in a program.")
SEGS = [SegmentIn(0, TEXT, "char=0-200")]


class Fake:
    locality = "local"
    type = "fake"

    def __init__(self, name, replies, context_window=8192):
        self.name, self.replies, self.calls = name, list(replies), []
        self.capabilities = Capabilities(text=True, context_window=context_window)

    def generate(self, messages, *, json_schema=None, max_tokens=None):
        self.calls.append(messages)
        r = self.replies.pop(0) if self.replies else self.replies_default
        if isinstance(r, Exception):
            raise r
        return GenResult(r if isinstance(r, str) else json.dumps(r), "fm", self.name)

    replies_default = "garbage"


def reg(*fakes):
    h = HeuristicBackend()
    h.type = "heuristic"
    bs = {f.name: f for f in fakes} | {"heuristic": h}
    return Registry(bs, {}, {"distill": [f.name for f in fakes]}, False)


def run(r, segs=SEGS, profile="generic"):
    return distill(r, segs, profile=profile, title="T", user_context="ctx")


def test_distill_collection_is_one_item_with_seven_entries():
    entries = [{"name": f"Tip {i}", "note": f"note {i}"} for i in range(1, 8)]
    f = Fake("f", [{"title": "7 tips", "entries": entries}])
    cands, by = run(reg(f), profile="collection")
    assert len(cands) == 1 and cands[0].kind == "collection"
    assert [e["name"] for e in cands[0].data["entries"]] == [e["name"] for e in entries]
    assert by == "f:fm"


def test_distill_valid_json_stated_insight_kept_and_fabricated_downgraded():
    out = {"summary": "s", "insights": [{"text": "own", "quote": "Borrowing lets code read without owning."},
                                        {"text": "fake", "quote": "Rust is a spreadsheet"}]}
    cands, _ = run(reg(Fake("f", [out])))
    ins = {c.title: c for c in cands if c.kind == "insight"}
    assert ins["own"].provenance == "stated" and ins["own"].segment_idx == 0
    assert ins["fake"].provenance == "inferred" and ins["fake"].data["flag"] == "evidence_not_found"


def test_distill_invalid_json_repairs_once():
    f = Fake("f", ["not json", {"summary": "ok", "insights": []}])
    cands, by = run(reg(f))
    assert len(f.calls) == 2 and by == "f:fm" and cands[0].body == "ok"
    assert "invalid" in f.calls[1][-1]["content"].lower()


def test_distill_invalid_json_repairs_then_falls_back_to_heuristic():
    f = Fake("f", [])
    cands, by = run(reg(f))
    assert len(f.calls) == 2 and by.startswith("heuristic")
    assert cands and all(c.provenance in ("stated", "inferred") for c in cands)
    assert any(c.provenance == "stated" for c in cands)  # heuristic quotes are real substrings


def test_distill_next_backend_before_heuristic_and_provider_error():
    bad = Fake("bad", [ProviderError("down")])
    good = Fake("good", [{"summary": "good one", "insights": []}])
    _, by = run(reg(bad, good))
    assert by == "good:fm" and len(bad.calls) == 1


def test_distill_schema_violation_counts_as_invalid():
    f = Fake("f", [{"summary": 5}, {"summary": 6}])
    _, by = run(reg(f))
    assert by.startswith("heuristic")


def test_distill_map_reduce_when_over_context():
    segs = [SegmentIn(i, f"Segment {i} " + "word " * 400, f"char={i}") for i in range(4)]
    part = {"summary": "part", "insights": [], "topics": ["t"]}
    f = Fake("f", [part, part, part, part, {"summary": "final"}], context_window=1500)
    cands, by = run(reg(f), segs)
    assert len(f.calls) == 5 and by == "f:fm"
    assert cands[0].body == "final"


def test_profile_for_and_schemas():
    assert set(SCHEMAS) == {"generic", "programming", "paper", "article", "collection"}
    assert profile_for("text", "top 7 tools") == "collection"
    assert profile_for("text", "python code") == "programming"
    assert profile_for("pdf", "research paper") == "paper"
    assert profile_for("web", "") == "article"
    assert profile_for("text", "") == "generic"


@pytest.mark.parametrize("profile", sorted(SCHEMAS))
def test_distill_every_profile_falls_back_to_heuristic(profile):
    for bad in (Fake("f", []), Fake("g", [ProviderError("down")])):
        cands, by = run(reg(bad), profile=profile)
        assert cands and by.startswith("heuristic")
    assert (len(cands) == 1) == (profile == "collection")


def test_distill_oversized_single_segment_is_split():
    segs = [SegmentIn(0, "word " * 2000, "char=0")]
    part = {"summary": "p", "insights": []}
    f = Fake("f", [part] * 5 + [{"summary": "final"}], context_window=1500)
    run(reg(f), segs)
    assert len(f.calls) >= 3 and all(len(c[1]["content"]) <= 3000 for c in f.calls[:-1])


@pytest.mark.parametrize("profile,bad", [
    ("programming", {"summary": "s", "snippets": [{"title": "t"}]}),
    ("paper", {"summary": "s", "claims": [{"quote": "q"}]}),
    ("collection", {"summary": "only a summary"}),
    ("collection", {"title": "t", "entries": []}),
])
def test_distill_real_backend_profile_violation_repairs_then_heuristic(profile, bad):
    f = Fake("f", [bad, bad])
    cands, by = run(reg(f), profile=profile)
    assert len(f.calls) == 2 and by.startswith("heuristic") and cands
    if profile == "collection":
        assert len(cands) == 1 and cands[0].data["entries"] is not None


def test_distill_normalize_never_raises_on_malformed_element(monkeypatch):
    from infoparser.pipeline import distill as D
    f = Fake("f", [{"summary": "s", "insights": [{"text": "ok"}]}])
    monkeypatch.setattr(D, "validate", lambda obj, schema, path="$": None)  # force past validation
    obj = {"summary": "s", "insights": [{"quote": "no text"}, {"text": "ok"}], "snippets": [{"title": "t"}]}
    assert [c.title for c in D.normalize(obj, "programming", SEGS)] == ["Summary", "ok"]
