"""Evidence checks: downgrade `stated`/`external` candidates whose proof does not hold."""
import re
from dataclasses import replace
from urllib.parse import urlsplit

from infoparser.domain.models import Candidate, SegmentIn


def norm(s: str) -> str:
    """Whitespace-collapsed, case-folded text for quote matching."""
    return re.sub(r"\s+", " ", s).strip().casefold()


MIN_QUOTE = 8  # non-whitespace characters a quote needs, unless it is the whole segment


def evidence_in(evidence: str | None, text: str) -> bool:
    """True when a meaningful quote occurs in text, ignoring case and whitespace runs.

    Meaningful: at least MIN_QUOTE non-whitespace characters, or the whole (shorter) text."""
    if not evidence:
        return False
    q, t = norm(evidence), norm(text)
    return q in t and (len(re.sub(r"\s", "", q)) >= MIN_QUOTE or q == t)


def _http_url(v) -> bool:
    """A well-formed http(s) URL string (host present, no whitespace)."""
    if not isinstance(v, str) or re.search(r"\s", v):
        return False
    try:
        u = urlsplit(v)
        return u.scheme in ("http", "https") and bool(u.hostname)
    except ValueError:  # e.g. an unbalanced "[" in the host
        return False


def check(candidates: list[Candidate], segments: list[SegmentIn]) -> list[Candidate]:
    """Return candidates with unprovable `stated`/`external` claims downgraded to `inferred`."""
    by_idx = {s.idx: s.text for s in segments}
    out = []
    for c in candidates:
        found = c.segment_idx in by_idx and evidence_in(c.evidence, by_idx[c.segment_idx])
        if c.provenance == "stated" and not found:
            c = replace(c, provenance="inferred", data={**c.data, "flag": "evidence_not_found"})
        elif c.provenance == "external" and not _http_url(c.data.get("url")):
            c = replace(c, provenance="inferred")
        out.append(c)
    return out
