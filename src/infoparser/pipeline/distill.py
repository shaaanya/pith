"""Distillation through registry ports only (never imports a concrete backend).

Per backend in chain("distill") (heuristic is always last): generate -> parse/validate against the
profile schema (empty text is invalid) -> on failure ONE repair retry -> on failure next backend.
Output is normalized into Candidates (accepts the heuristic shape
{"summary","insights":[{"text","quote"}]} like any other), then passes provenance.check. Inputs over
the generator's context window are map-reduced.
"""
import json
import re

from infoparser.domain.models import Candidate, SegmentIn
from infoparser.providers.ports import ProviderError

from .provenance import check, evidence_in
from .schemas import SCHEMAS, validate

_CHARS_PER_TOKEN = 3  # conservative
_OVERHEAD = 1500  # chars reserved for instructions/schema
_SUMMARY_SCHEMA = {"type": "object", "required": ["summary"],
                   "properties": {"summary": {"type": "string", "minLength": 1}}}


def _system(profile, title, user_context):
    return (f"You distill a source titled {title!r} into knowledge items (profile: {profile}). "
            f"User context: {user_context or 'none'}. Only state what the text says; quotes "
            "must be copied verbatim from the text. "
            "Reply with ONLY JSON matching the given schema.")


_SCAN_CHARS = 256 * 1024  # a reply is never legitimately larger; bounds hostile input
_MAX_STARTS = 200  # '{' positions tried before giving up


def _first_object(text: str):
    """The first balanced JSON object embedded in `text` (prose and fences around it ignored).

    Work is bounded: only the first 256 KB are scanned and at most 200 '{' start positions are
    tried, so hostile output cannot cost quadratic time."""
    decoder = json.JSONDecoder(strict=False)
    text = text[:_SCAN_CHARS]
    pos = -1
    for _ in range(_MAX_STARTS):
        pos = text.find("{", pos + 1)
        if pos < 0:
            return None
        try:
            obj, _ = decoder.raw_decode(text, pos)
        except (ValueError, RecursionError):
            continue
        if isinstance(obj, dict):
            return obj
    return None


def _parse(text: str):
    """Parse a model reply: bare JSON, a fenced block, or an object inside prose.

    Only parses; the caller still validates against the schema (nothing is invented). Raw control
    characters inside strings (e.g. a hard line wrap) are tolerated."""
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        return json.loads(t, strict=False)
    except (ValueError, RecursionError):
        return _first_object(t)


def _ask(backend, msgs, schema, lenient=False, profile=None):
    """One generate + one repair retry. Returns (obj, GenResult) or (None, None).
    ProviderError propagates."""
    for _ in range(2):
        res = backend.generate(msgs, json_schema=schema)
        obj = _parse(res.text)
        err = "not valid JSON" if obj is None else validate(obj, schema)
        # only the final heuristic fallback may answer in the generic shape; normalize() adapts it
        if lenient and obj is not None and err and validate(obj, SCHEMAS["generic"]) is None:
            err = None
        if err is None and profile == "collection" and not lenient and not obj.get("entries"):
            err = "'entries' must not be empty"
        if err is None:
            return obj, res
        msgs = [*msgs, {"role": "assistant", "content": res.text},
                {"role": "user", "content": f"Your reply was invalid ({err}). "
                                            "Reply with ONLY valid JSON matching the schema."}]
    return None, None


def _batches(segments, budget):
    """Group segments so each batch's text (joined by 2-char separators) fits budget;
    oversized segments are split."""
    pieces = []
    for s in segments:
        if len(s.text) <= budget:
            pieces.append(s)
        else:
            pieces += [SegmentIn(s.idx, s.text[a:a + budget], s.locator)
                       for a in range(0, len(s.text), budget)]
    batch, size = [], 0
    for s in pieces:
        if batch and size + len(s.text) + 2 > budget:
            yield batch
            batch, size = [], 0
        batch.append(s)
        size += len(s.text) + 2
    if batch:
        yield batch


def _text(segs):
    return "\n\n".join(s.text for s in segs)


def _msgs(system, user):
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _merge(parts):
    merged = {**parts[0]}
    for k in ("insights", "entries", "claims", "snippets", "key_points", "topics", "entities"):
        if any(k in p for p in parts):
            merged[k] = [x for p in parts for x in p.get(k, [])]
    return merged


def _reduce(backend, system, parts, last):
    """Merge map-phase parts; combine their summaries (falling back to the joined partials)."""
    merged = _merge(parts)
    sums = "\n\n".join(p.get("summary", "") for p in parts if p.get("summary"))
    if sums:
        ask = "Combine these partial summaries into one summary:\n\n" + sums
        obj, res = _ask(backend, _msgs(system, ask), _SUMMARY_SCHEMA)
        merged["summary"] = obj["summary"] if obj else sums
        last = res or last
    return merged, last


def _run_backend(backend, segments, profile, title, user_context):
    schema, system = SCHEMAS[profile], _system(profile, title, user_context)
    lenient = backend.type == "heuristic"
    budget = max(500, backend.capabilities.context_window * _CHARS_PER_TOKEN - _OVERHEAD)
    if sum(len(s.text) + 2 for s in segments) <= budget:
        return _ask(backend, _msgs(system, _text(segments)), schema, lenient, profile)
    parts, last = [], None
    for batch in _batches(segments, budget):  # map
        obj, last = _ask(backend, _msgs(system, _text(batch)), schema, lenient, profile)
        if obj is None:
            return None, None
        parts.append(obj)
    return _reduce(backend, system, parts, last)


def _locate(quote, segments):
    return next((s.idx for s in segments if evidence_in(quote, s.text)), None)


def _converters(obj, item):
    """(elements, converter) pairs for the list-valued fields of a distillation object."""
    def snippet(x):
        return item("snippet", x["title"], x["title"], x.get("quote"), {"code": x["code"]})

    convs = [(obj.get(k, []), lambda i, kind=kind: item(kind, i["text"], i["text"], i.get("quote")))
             for k, kind in (("insights", "insight"), ("claims", "claim"))]
    convs.append((obj.get("snippets", []), snippet))
    convs.append((obj.get("key_points", []), lambda p: item("insight", p, p, None)))
    return convs


def normalize(obj: dict, profile: str, segments: list[SegmentIn],
              title: str = "") -> list[Candidate]:
    """Turn a validated model object (any profile shape) into Candidates."""
    common = {"topics": list(obj.get("topics", [])), "entities": list(obj.get("entities", []))}

    def item(kind, name, body, quote, data=None):
        stated = bool(quote)
        return Candidate(kind=kind, title=name, body=body, data=data or {}, evidence=quote or None,
                         provenance="stated" if stated else "inferred",
                         segment_idx=_locate(quote, segments) if stated else None, **common)

    if profile == "collection":
        entries = obj.get("entries") or [{"name": i["text"], "quote": i.get("quote")}
                                         for i in obj.get("insights", [])]
        title = obj.get("title") or title
        return [Candidate(kind="collection", title=title, body=obj.get("summary") or title,
                          data={"entries": entries}, **common)]
    out = [Candidate(kind="summary", title="Summary", body=obj["summary"], **common)]
    for elems, conv in _converters(obj, item):
        for e in elems:
            try:  # one malformed element must not sink the whole result
                out.append(conv(e))
            except (KeyError, TypeError, AttributeError):
                continue
    return out


def distill(registry, segments, *, profile, title, user_context):
    """Distil `segments` through the first backend in chain("distill") that yields valid output.

    Returns (candidates, "backend:model"); raises ProviderError only if even the heuristic fails."""
    for backend in registry.chain("distill"):
        try:
            obj, res = _run_backend(backend, segments, profile, title, user_context)
        except ProviderError:
            continue
        if obj is None:
            continue
        try:
            cands = normalize(obj, profile, segments, title)
        except (KeyError, TypeError, AttributeError):
            continue
        return check(cands, segments), f"{res.backend}:{res.model}"
    raise ProviderError("no backend produced valid distillation output")
