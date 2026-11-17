"""Empty model output is invalid: it takes the repair -> next backend -> heuristic path."""
import pytest
from test_distill import SEGS, Fake, reg

from pith.pipeline.distill import distill
from pith.pipeline.schemas import SCHEMAS, validate

GOOD = {"summary": "Rust ownership prevents data races.", "insights": []}
BAD = [
    ("article", {"summary": ""}),
    ("article", {"summary": "   \n\t"}),
    ("article", {"summary": None}),
    ("article", {"summary": "ok", "insights": [{"text": ""}]}),
    ("article", {"summary": "ok", "insights": [{"text": "  ", "quote": "x"}]}),
    ("article", {"summary": "ok", "key_points": ["fine", ""]}),
    ("programming", {"summary": "ok", "snippets": [{"title": "", "code": "x = 1"}]}),
    ("programming", {"summary": "ok", "snippets": [{"title": "t", "code": " "}]}),
    ("paper", {"summary": "ok", "claims": [{"text": ""}]}),
    ("collection", {"title": "List", "entries": [{"name": ""}]}),
    ("collection", {"title": "", "entries": [{"name": "a"}]}),
]


@pytest.mark.parametrize("profile,payload", BAD)
def test_schema_rejects_empty(profile, payload):
    """validate() reports an error for every empty-text variant."""
    assert validate(payload, SCHEMAS[profile]) is not None


@pytest.mark.parametrize("profile,payload", BAD)
def test_empty_output_falls_through_to_heuristic(profile, payload):
    """A backend that keeps answering with empty text ends in the heuristic fallback."""
    fake = Fake("f", [payload, payload])
    cands, by = distill(reg(fake), SEGS, profile=profile, title="T", user_context="")
    assert by == "heuristic:heuristic" and len(fake.calls) == 2  # first try + one repair
    assert all(c.body.strip() and c.title.strip() for c in cands)


def test_repair_retry_can_recover_from_empty_summary():
    """The repair retry is used: an empty summary followed by a valid one is accepted."""
    fake = Fake("f", [{"summary": ""}, GOOD])
    cands, by = distill(reg(fake), SEGS, profile="article", title="T", user_context="")
    assert by == "f:fm" and cands[0].body == GOOD["summary"]
