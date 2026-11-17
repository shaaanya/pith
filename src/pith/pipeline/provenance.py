"""Evidence checks: downgrade `stated`/`external` candidates whose proof does not hold."""
import json
import re
from dataclasses import replace
from urllib.parse import urlsplit

from pith.domain.models import Candidate, SegmentIn


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
            c = replace(c, provenance="inferred", evidence=None, data={
                **c.data, "flag": "evidence_not_found",
                **({"claimed_evidence": c.evidence} if c.evidence else {})})
        elif c.provenance == "external" and not _http_url(c.data.get("url")):
            c = replace(c, provenance="inferred")
        out.append(c)
    return out


def recheck_edited(conn, source_id: str) -> None:
    """After a reprocess, re-prove the `stated` items the user edited (they are kept as they are).

    The quote must still occur in a cited segment; else the citation moves to the segment that has
    it; else the item is downgraded to `inferred` and the quote is kept only as `claimed_evidence`
    (never displayed as source evidence). Runs inside the caller's transaction."""
    texts = dict(conn.execute("SELECT id, text FROM segments WHERE source_id=?", (source_id,)))
    for r in conn.execute("SELECT id, data_json, segment_refs FROM knowledge_items WHERE"
                          " source_id=? AND user_edited=1 AND deleted_at IS NULL AND"
                          " provenance='stated'", (source_id,)).fetchall():
        data, refs = json.loads(r["data_json"] or "{}"), json.loads(r["segment_refs"] or "[]")
        quote = data.get("evidence")
        if any(evidence_in(quote, texts[i]) for i in refs if i in texts):
            continue
        moved = next((i for i, t in texts.items() if evidence_in(quote, t)), None)
        if moved is not None:
            conn.execute("UPDATE knowledge_items SET segment_refs=? WHERE id=?",
                         (json.dumps([moved]), r["id"]))
            continue
        data = {**{k: v for k, v in data.items() if k != "evidence"},
                "flag": "evidence_not_found", **({"claimed_evidence": quote} if quote else {})}
        conn.execute("UPDATE knowledge_items SET provenance='inferred', flagged=1, data_json=?"
                     " WHERE id=?", (json.dumps(data), r["id"]))
