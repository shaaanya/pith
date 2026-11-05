from infoparser.domain.models import Candidate, SegmentIn
from infoparser.pipeline.provenance import check

SEGS = [SegmentIn(0, "Rust has   no garbage collector.", "char=0-10"), SegmentIn(1, "Other text.", "char=11-20")]


def C(**kw):
    base = dict(kind="insight", title="t", body="b", data={}, provenance="stated", evidence=None,
                segment_idx=0, confidence=None, entities=[], topics=[])
    return Candidate(**{**base, **kw})


def test_provenance_stated_with_real_quote_kept():
    [c] = check([C(evidence="rust HAS no garbage   collector")], SEGS)
    assert c.provenance == "stated" and "flag" not in c.data


def test_provenance_fabricated_quote_downgraded():
    out = check([C(evidence="Rust is slow"), C(evidence="Other text", segment_idx=0),
                 C(evidence="Other text", segment_idx=9), C(evidence=None)], SEGS)
    assert all(c.provenance == "inferred" and c.data["flag"] == "evidence_not_found" for c in out)


def test_provenance_external_requires_url():
    a, b = check([C(provenance="external"), C(provenance="external", data={"url": "https://x.y"})], SEGS)
    assert a.provenance == "inferred" and b.provenance == "external"


def test_check_does_not_mutate_inputs():
    orig = C(evidence="nope", data={"k": 1})
    out = check([orig], SEGS)
    assert orig.provenance == "stated" and orig.data == {"k": 1} and out[0] is not orig
