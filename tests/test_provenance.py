"""Provenance check: quotes must be found in the cited segment."""
from infoparser.domain.models import Candidate, SegmentIn
from infoparser.pipeline.provenance import check

SEGS = [SegmentIn(0, "Rust has   no garbage collector.", "char=0-10"),
        SegmentIn(1, "Other text.", "char=11-20")]


def make_candidate(**kw):
    """Candidate with defaults."""
    base = {"kind": "insight", "title": "t", "body": "b", "data": {}, "provenance": "stated",
            "evidence": None, "segment_idx": 0, "confidence": None, "entities": [], "topics": []}
    return Candidate(**{**base, **kw})


def test_provenance_stated_with_real_quote_kept():
    """A stated claim with a real quote is kept."""
    out = check([make_candidate(evidence="rust HAS no garbage   collector")], SEGS)
    assert len(out) == 1
    c = out[0]
    assert c.provenance == "stated" and "flag" not in c.data


def test_provenance_fabricated_quote_downgraded():
    """Missing or mislocated quotes downgrade to inferred."""
    out = check([make_candidate(evidence="Rust is slow"),
                 make_candidate(evidence="Other text", segment_idx=0),
                 make_candidate(evidence="Other text", segment_idx=9),
                 make_candidate(evidence=None)], SEGS)
    assert all(c.provenance == "inferred" and c.data["flag"] == "evidence_not_found" for c in out)


def test_provenance_external_requires_url():
    """External provenance needs a url."""
    out = check([make_candidate(provenance="external"),
                 make_candidate(provenance="external", data={"url": "https://x.y"})], SEGS)
    a, b = out[0], out[1]
    assert a.provenance == "inferred" and b.provenance == "external"


def test_check_does_not_mutate_inputs():
    """check returns copies."""
    orig = make_candidate(evidence="nope", data={"k": 1})
    out = check([orig], SEGS)
    assert orig.provenance == "stated" and orig.data == {"k": 1} and out[0] is not orig
