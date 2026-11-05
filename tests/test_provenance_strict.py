"""stated needs a meaningful quote; external needs a real http(s) URL."""
import json

import pytest

from infoparser.domain.models import Candidate, SegmentIn
from infoparser.pipeline.provenance import check
from infoparser.providers.heuristic import HeuristicBackend

LONG = SegmentIn(0, "Rust has no garbage collector and uses ownership.", "char=0-50")
SHORT = SegmentIn(1, "Use Rust.", "char=51-60")


def _cand(**kw):
    base = {"kind": "insight", "title": "t", "body": "b", "data": {}, "provenance": "stated",
            "evidence": None, "segment_idx": 0, "confidence": None, "entities": [], "topics": []}
    return Candidate(**{**base, **kw})


def test_trivial_quote_is_downgraded():
    """Quoting a trivial word no longer makes an item 'stated'."""
    c = check([_cand(evidence="Rust")], [LONG])[0]
    assert c.provenance == "inferred" and c.data["flag"] == "evidence_not_found"


def test_meaningful_quote_and_whole_short_segment_stay_stated():
    """8+ non-space characters pass; a segment shorter than that must be quoted whole."""
    out = check([_cand(evidence="no garbage collector"),
                             _cand(evidence="use rust.", segment_idx=1),
                       _cand(evidence="Use", segment_idx=1)], [LONG, SHORT])
    assert [c.provenance for c in out] == ["stated", "stated", "inferred"]
    tiny = SegmentIn(2, "Hi there", "char=0-8")  # 7 non-space characters
    out = check([_cand(evidence="hi there", segment_idx=2),
                 _cand(evidence="there", segment_idx=2)], [tiny])
    assert [c.provenance for c in out] == ["stated", "inferred"]


def test_heuristic_backend_quotes_stay_stated():
    """Heuristic output (quote == sentence) still validates as stated for ordinary sentences."""
    text = "Sourdough needs a long fermentation. Hydration changes the crumb a lot.\nShort one."
    out = HeuristicBackend().generate([{"role": "user", "content": text}], json_schema={})
    quotes = [i["quote"] for i in json.loads(out.text)["insights"]]
    segs = [SegmentIn(0, text, "char=0-80")]
    got = check([_cand(evidence=q) for q in quotes], segs)
    assert quotes and all(c.provenance == "stated" for c in got)


@pytest.mark.parametrize("url", [None, "", "x", "javascript:alert(1)", "ftp://x.org/a", "https://",
                                 "http://has space.org", "http://[::1", 5, ["https://x.org"]])
def test_external_needs_a_wellformed_http_url(url):
    """external keeps its provenance only with a real http(s) URL."""
    c = check([_cand(provenance="external", data={"url": url})], [LONG])[0]
    assert c.provenance == "inferred"


def test_external_with_http_url_kept():
    """A well-formed http or https URL passes."""
    out = check([_cand(provenance="external", data={"url": u}) for u in
                 ("https://example.org/a?b=1", "http://example.org")], [LONG])
    assert [c.provenance for c in out] == ["external", "external"]
