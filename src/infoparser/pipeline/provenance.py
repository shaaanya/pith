import re
from dataclasses import replace

from infoparser.domain.models import Candidate, SegmentIn


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().casefold()


def evidence_in(evidence: str | None, text: str) -> bool:
    return bool(evidence) and norm(evidence) in norm(text)


def check(candidates: list[Candidate], segments: list[SegmentIn]) -> list[Candidate]:
    by_idx = {s.idx: s.text for s in segments}
    out = []
    for c in candidates:
        if c.provenance == "stated" and not (c.segment_idx in by_idx and evidence_in(c.evidence, by_idx[c.segment_idx])):
            c = replace(c, provenance="inferred", data={**c.data, "flag": "evidence_not_found"})
        elif c.provenance == "external" and not c.data.get("url"):
            c = replace(c, provenance="inferred")
        out.append(c)
    return out
