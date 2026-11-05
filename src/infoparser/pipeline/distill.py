"""Distillation through registry ports only (never imports a concrete backend).

Per backend in chain("distill") (heuristic is always last): generate -> parse/validate against the
profile schema -> on failure ONE repair retry -> on failure next backend. Output is normalized into
Candidates (accepts the heuristic shape {"summary","insights":[{"text","quote"}]} like any other),
then passes provenance.check. Inputs over the generator's context window are map-reduced.
"""
import json
import re

from infoparser.domain.models import Candidate, SegmentIn
from infoparser.providers.ports import ProviderError

from .provenance import check, evidence_in
from .schemas import SCHEMAS, validate

_CHARS_PER_TOKEN = 3  # conservative
_OVERHEAD = 1500  # chars reserved for instructions/schema
_SUMMARY_SCHEMA = {"type": "object", "required": ["summary"], "properties": {"summary": {"type": "string"}}}


def _system(profile, title, user_context):
    return (f"You distill a source titled {title!r} into knowledge items (profile: {profile}). "
            f"User context: {user_context or 'none'}. Only state what the text says; quotes must be copied "
            "verbatim from the text. Reply with ONLY JSON matching the given schema.")


def _parse(text: str):
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    try:
        return json.loads(t)
    except ValueError:
        a, b = t.find("{"), t.rfind("}")
        if a >= 0 < b:
            try:
                return json.loads(t[a:b + 1])
            except ValueError:
                pass
    return None


def _ask(backend, system, user, schema):
    """One generate + one repair retry. Returns (obj, GenResult) or (None, None). ProviderError propagates."""
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    for attempt in range(2):
        res = backend.generate(msgs, json_schema=schema)
        obj = _parse(res.text)
        err = "not valid JSON" if obj is None else validate(obj, schema)
        # any backend (the heuristic one included) may answer in the generic shape; normalize() adapts it
        if obj is not None and err and validate(obj, SCHEMAS["generic"]) is None:
            err = None
        if err is None:
            return obj, res
        msgs = [*msgs, {"role": "assistant", "content": res.text},
                {"role": "user", "content": f"Your reply was invalid ({err}). Reply with ONLY valid JSON matching the schema."}]
    return None, None


def _batches(segments, budget):
    """Group segments so each batch's text (joined by 2-char separators) fits budget; split oversized segments."""
    pieces = []
    for s in segments:
        if len(s.text) <= budget:
            pieces.append(s)
        else:
            pieces += [SegmentIn(s.idx, s.text[a:a + budget], s.locator) for a in range(0, len(s.text), budget)]
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


def _run_backend(backend, segments, profile, title, user_context):
    schema, system = SCHEMAS[profile], _system(profile, title, user_context)
    budget = max(500, backend.capabilities.context_window * _CHARS_PER_TOKEN - _OVERHEAD)
    if sum(len(s.text) + 2 for s in segments) <= budget:
        return _ask(backend, system, _text(segments), schema)
    parts, last = [], None
    for batch in _batches(segments, budget):  # map
        obj, last = _ask(backend, system, _text(batch), schema)
        if obj is None:
            return None, None
        parts.append(obj)
    merged = {**parts[0]}
    for k in ("insights", "entries", "claims", "snippets", "key_points", "topics", "entities"):
        if any(k in p for p in parts):
            merged[k] = [x for p in parts for x in p.get(k, [])]
    sums = "\n\n".join(p.get("summary", "") for p in parts if p.get("summary"))
    if sums:  # reduce: summary-of-summaries; fall back to the joined partials
        o, r = _ask(backend, system, "Combine these partial summaries into one summary:\n\n" + sums, _SUMMARY_SCHEMA)
        merged["summary"] = o["summary"] if o else sums
        last = r or last
    return merged, last


def _locate(quote, segments):
    return next((s.idx for s in segments if evidence_in(quote, s.text)), None)


def normalize(obj: dict, profile: str, segments: list[SegmentIn], title: str = "") -> list[Candidate]:
    topics, entities = list(obj.get("topics", [])), list(obj.get("entities", []))
    common = dict(topics=topics, entities=entities)

    def item(kind, title, body, quote, data=None):
        stated = bool(quote)
        return Candidate(kind=kind, title=title, body=body, data=data or {}, evidence=quote or None,
                         provenance="stated" if stated else "inferred",
                         segment_idx=_locate(quote, segments) if stated else None, **common)

    if profile == "collection":
        entries = obj.get("entries") or [{"name": i["text"], "quote": i.get("quote")} for i in obj.get("insights", [])]
        title = obj.get("title") or title
        return [Candidate(kind="collection", title=title, body=obj.get("summary") or title,
                          data={"entries": entries}, **common)]
    out = [Candidate(kind="summary", title="Summary", body=obj["summary"], **common)]
    for key, kind in (("insights", "insight"), ("claims", "claim")):
        out += [item(kind, i["text"], i["text"], i.get("quote")) for i in obj.get(key, [])]
    out += [item("snippet", s["title"], s["title"], s.get("quote"), {"code": s["code"]}) for s in obj.get("snippets", [])]
    out += [item("insight", p, p, None) for p in obj.get("key_points", [])]
    return out


def distill(registry, segments, *, profile, title, user_context):
    for backend in registry.chain("distill"):
        try:
            obj, res = _run_backend(backend, segments, profile, title, user_context)
        except ProviderError:
            continue
        if obj is None:
            continue
        return check(normalize(obj, profile, segments, title), segments), f"{res.backend}:{res.model}"
    raise ProviderError("no backend produced valid distillation output")
