"""Knowledge notes: the model EXTRACTS typed units, ordinary code verifies, repairs and COMPOSES.

Why this shape (measured on gemma4:e4b, see eval/notes): a small local model asked for "a summary and
3-7 insights" writes commentary about the source. Asked only to list concrete units it keeps names,
numbers and steps, and everything that must not be wrong (numbers, term spelling, support, layout,
length) is then decided by code, with no extra model call.

Flow: repair_terms (description beats a noisy transcript) -> extract units (1 call; map over batches
for long sources, recall first) -> verify (drop unsupported numbers/claims, meta-commentary, promo)
-> optional intent-focused pass -> compose markdown -> mention index. Candidates returned:
one `note`, one `mentions` (searchable index of every named thing), and one `unit` per kept unit.
"""
import difflib
import re
import time

from pith.domain.models import Candidate, SegmentIn
from pith.providers.ports import ProviderError

from .distill import _CHARS_PER_TOKEN, _OVERHEAD, _ask, _batches, _msgs

VERSION = "note-v1"
HEADINGS = {"step": "Steps", "fact": "Facts", "claim": "Claims", "definition": "Definitions",
            "resource": "Resources", "warning": "Caveats"}
_SYN = {"action": "step", "instruction": "step", "procedure": "step", "number": "fact",
        "statistic": "fact", "entity": "resource", "reference": "resource", "tool": "resource",
        "book": "resource", "argument": "claim", "opinion": "claim", "caveat": "warning",
        "limitation": "warning", "example": "fact"}
_STR = {"type": "string"}
_NES = {"type": "string", "minLength": 1}
SCHEMA = {"type": "object", "required": ["units"], "properties": {
    "context": _STR,
    "units": {"type": "array", "items": {"type": "object", "required": ["type", "text"],
                                         "properties": {"type": _NES, "text": _NES}}},
    "entities": {"type": "array", "items": _STR}, "gaps": {"type": "array", "items": _STR}}}

PROMPT = (
    "You turn a saved source into notes the user will read INSTEAD of the original. Extract EVERY "
    "concrete piece of information as units, in source order. One unit = one self-contained "
    "sentence or step.\n"
    "Unit types: step (an action to take, in order), fact (a number, name, date, event or "
    "specification), claim (an opinion or argument with its reason; say who holds it), definition, "
    "resource (a book, tool, site, skill or person to look up: give its exact name), warning (a "
    "limit, caveat, exception or unverified claim).\n"
    "Rules:\n"
    "- Copy exact names, numbers, commands, identifiers and config values. Never write 'some "
    "tools' or 'several steps': name them.\n"
    "- State the information itself. Never describe the source ('the video explains', 'the "
    "author discusses').\n"
    "- Use only what the text says. Do not add steps, numbers, schedules or advice. If the source "
    "promises more than it gives (for example '10 tips' but only 4 are given), say so in gaps "
    "(never for promotional offers such as a free guide or newsletter).\n"
    "- Write each unit as a clean, capitalised sentence in your own words, not a copy of speech "
    "fillers; keep every name, number and command exactly.\n"
    "- Skip greetings, self-promotion and calls to action (like, follow, comment, link in bio, "
    "discounts, newsletters).\n"
    "- If the DESCRIPTION and the TRANSCRIPT spell a name differently, use the DESCRIPTION "
    "spelling.\n"
    "- Spoken punctuation inside commands must be written as symbols: 'dash t flaskapp dot' -> "
    "'-t flaskapp .', 'colon' -> ':', 'underscore' -> '_', 'slash' -> '/'.\n"
    "- If the speaker corrects an earlier statement ('correction', 'I was wrong', 'not X'), keep "
    "ONLY the corrected value and add a caveat unit saying it was corrected. Never keep both.\n"
    "- context: one short plain phrase naming the subject, starting with the subject itself, e.g. "
    "'Interview prep plan for a Payments engineering role'. Name the speaker only if the source "
    "does. Never start with 'This source' or 'This video'.\n"
    "- entities: every named person, company, product, tool, library, book, command, skill, even "
    "if mentioned once.\n"
    "{intent}Reply with ONLY JSON: "
    '{{"context": str, "units": [{{"type": str, "text": str}}], "entities": [str], "gaps": [str]}}')
_INTENT = ("The user saved this because: \"{}\". Include everything relevant to that in full "
           "detail (exact names, commands, numbers), then the rest.\n")
_INTENT_ONLY = ("The user saved this for ONE reason: \"{}\". Extract only what the text says about "
                "it, with exact names, commands and numbers.\n")

# ---------------------------------------------------------------------------------- repair

_WORD = re.compile(r"[A-Za-z][A-Za-z0-9'’\-]*")
_NUMWORDS = {w: str(i) for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve".split())}


def _key(s):
    return re.sub(r"[^a-z0-9]", "", s.casefold())


def _terms(ref):
    """key -> display form for every 1- to 4-word term (>= 6 letters) of the reference text."""
    toks = [re.sub(r"['’]s$", "", w) for w in _WORD.findall(ref)]
    out = {}
    for n in (1, 2, 3, 4):
        for i in range(len(toks) - n + 1):
            k = _key("".join(toks[i:i + n]))
            if len(k) >= 6:
                out.setdefault(k, " ".join(toks[i:i + n]))
    return out


def _trim(words, text, term):
    """Drop leading/trailing words the heard span and the term share ("learn item potency" vs
    "learn idempotency" -> "item potency" vs "idempotency"), so neighbours are never rewritten."""
    tw = term.split()
    lo, hi = 0, len(words)
    while lo < hi and tw and words[lo].group().casefold() == tw[0].casefold():
        lo, tw = lo + 1, tw[1:]
    while hi > lo and tw and words[hi - 1].group().casefold() == tw[-1].casefold():
        hi, tw = hi - 1, tw[:-1]
    if lo == hi or not tw:
        return words[0].start(), words[-1].end(), text[words[0].start():words[-1].end()], None
    a, b = words[lo].start(), words[hi - 1].end()
    return a, b, text[a:b], " ".join(tw)


_SPOKEN = re.compile(r"\b(dash|dot|colon|underscore|slash)\b", re.I)


_FLAGJOIN = re.compile(r"(?<!\w)(--[a-z]+(?:-[a-z]+)*) (file|dir|path|cache|only|name|mode|size|limit)\b", re.I)


def despeak(text, force=False):
    """Dictated code to symbols: "dash dash env dot env" -> "--env .env", "80 colon 8000" ->
    "80:8000", "reverse underscore proxy" -> "reverse_proxy". Only for text that clearly is
    dictation (3+ spoken symbols); ordinary prose ("a dash of salt") is left alone."""
    if not force and len(_SPOKEN.findall(text)) < 3:
        return text
    t = re.sub(r"\bdash dash (?=\w)", "--", text, flags=re.I)
    t = re.sub(r"\bdash (?=\w)", "-", t, flags=re.I)
    t = _FLAGJOIN.sub(lambda m: m.group(1) + "-" + m.group(2), t)
    t = _FLAGJOIN.sub(lambda m: m.group(1) + "-" + m.group(2), t)  # --no cache dir -> --no-cache-dir
    t = re.sub(r"\s*\bunderscore\s*", "_", t, flags=re.I)
    t = re.sub(r"\s*\bcolon\s*", ":", t, flags=re.I)
    t = re.sub(r"\s*\bslash\s*", "/", t, flags=re.I)
    t = re.sub(r"(^|\s)dot (?=\w)", r"\1.", t, flags=re.I)  # "dot env" -> ".env"
    t = re.sub(r"(?<=\w) dot\.?(?=\s|$)", " .", t, flags=re.I)  # "flaskapp dot." -> "flaskapp ."
    return t


_ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen " \
        "sixteen seventeen eighteen nineteen".split()
_TENS = "twenty thirty forty fifty sixty seventy eighty ninety".split()
_NUMPHRASE = re.compile(
    rf"\b(?:(?P<t>{'|'.join(_TENS)})(?:[- ](?P<o>one|two|three|four|five|six|seven|eight|nine))?"
    rf"|(?P<s>{'|'.join(_ONES)})(?: (?P<m>hundred|thousand))?)\b", re.I)
_MEASURE = re.compile(r" (?:ml|l|kg|g|mg|km|cm|mm|ms|kb|mb|gb|tb|percent|minutes?|hours?|seconds?|days?|"
                      r"weeks?|months?|years?|times|tasks?|items?|nodes?|steps?)\b")


def numerals(text):
    """Spoken quantities to digits: "limit fifty" -> "limit 50", "forty-five minutes" -> "45 minutes",
    "five hundred ml" -> "500 ml". A bare small number ("at five", "one of") is left alone unless a
    unit follows, and a capitalised phrase inside a sentence ("Four Thousand Weeks") is a title."""
    def sub(m):
        w = m.group(0)
        if w[:1].isupper() and m.start() and not re.search(r"[.!?:]\s+$|\n\s*$", text[:m.start()]):
            return w
        if m.group("t"):
            n = (_TENS.index(m.group("t").lower()) + 2) * 10
            n += _ONES.index(m.group("o").lower()) if m.group("o") else 0
            return str(n)
        n = _ONES.index(m.group("s").lower())
        if m.group("m"):
            return str(n * (100 if m.group("m").lower() == "hundred" else 1000))
        return str(n) if _MEASURE.match(text, m.end()) else w
    return _NUMPHRASE.sub(sub, text)


def repair_terms(segments, title=""):
    """Fix transcript mishearings of terms that the author's description spells correctly.

    "item potency" -> "idempotency", "dynamo db" -> "DynamoDB": a 1-3 word transcript window whose
    letters match a description term (exactly, or >= 0.86 similar) is replaced by that term.
    Returns (segments, [(heard, term)]); the stored evidence segments are never touched, only the
    copy the model reads. Nothing happens without a description, and uncertain matches are left."""
    ref = " ".join(s.text for s in segments if s.locator == "description") + " " + title
    terms = _terms(ref)
    dictated = sum(len(_SPOKEN.findall(g.text)) for g in segments if g.locator != "description") >= 3
    spoken = [SegmentIn(g.idx, numerals(despeak(g.text, dictated) if g.locator != "description"
                                           else g.text), g.locator) for g in segments]
    changed = [(g.text, n.text) for g, n in zip(segments, spoken) if g.text != n.text]
    segments = spoken
    if not terms:
        return segments, [("dictated symbols and number words", "converted")] if changed else []
    ref_fold, repairs, out = ref.casefold(), {}, []
    if changed:
        repairs["dictated"] = ("dictated symbols (dash, dot, colon...) and number words", "converted")
    buckets = {}  # (first letter, length) -> terms, so a window is only compared with look-alikes
    for t in terms:
        buckets.setdefault((t[0], len(t)), []).append(t)
    for seg in segments:
        if seg.locator == "description":
            out.append(seg)
            continue
        words = list(_WORD.finditer(seg.text))
        subs, i = [], 0
        while i < len(words):
            hit = None
            for n in (4, 3, 2, 1):
                if i + n > len(words):
                    continue
                a, b = words[i].start(), words[i + n - 1].end()
                heard = seg.text[a:b]
                k = _key(heard)
                if len(k) < 6 or heard.casefold() in ref_fold:
                    continue
                term = terms.get(k)
                if term and len(term.split()) > n:  # never split a word the speaker said as one
                    term = None
                if term is None:
                    near = [t for d in range(-2, 3) for t in buckets.get((k[0], len(k) + d), ())]
                    best = difflib.get_close_matches(k, near, n=1, cutoff=0.86)
                    term = terms[best[0]] if best else None
                    # a fuzzy match is only safe for names: one long word or a Capitalised phrase
                    if term and len(term.split()) > 1 and not all(w[:1].isupper() for w in term.split()):
                        term = None
                    if term and len(term.split()) == 1 and len(term) < 7:
                        term = None
                if term:
                    a, b, heard, term = _trim(words[i:i + n], seg.text, term)
                if term and term.casefold() != heard.casefold():
                    hit = (a, b, n, heard, term)
                    break
            if hit:
                subs.append((hit[0], hit[1], hit[4]))
                repairs[hit[3].casefold()] = (hit[3], hit[4])
                i += hit[2]
            else:
                i += 1
        text = seg.text
        for a, b, term in reversed(subs):
            text = text[:a] + term + text[b:]
        out.append(SegmentIn(seg.idx, text, seg.locator))
    return out, list(repairs.values())


# ---------------------------------------------------------------------------------- verify

_STOP = set("the and for that with this from have are was were will you your they them their "
            "there then than what when which who how not but can all any more some into about "
            "over also just like out has had its our one two creator author speaker host says said "
            "states stated mentions mention does doesn use uses used using".split())
_META = re.compile(r"\b(video|creator|author|speaker|speakers|article|source|text|presenter|"
                   r"podcast|post|tutorial|reel|host|narrator)\b.{0,30}\b(discuss|explain|provid|"
                   r"outlin|cover|explor|offer|describ|present|emphasi|encourag|highlight|walk|"
                   r"share|talk|go over|dive)\w*", re.I)
_PROMO = re.compile(r"\b(link in (my )?bio|dm (me|you)|like button|smash|subscribe|"
                    r"(comment|follow|like)\b.{0,40}\b(guide|template|more|channel|video|button)|"
                    r"\d+% off|use code)", re.I)


def _words(s):
    return re.findall(r"[a-z0-9]+", s.casefold())


def _stems(s):
    return {w[:4] for w in _words(s) if w not in _STOP and len(w) > 2 and not w.isdigit()}


def _nums(s):
    """Numbers of 2+ digits (or with a decimal point) as normalised strings."""
    found = {m.rstrip(".").replace(",", "") for m in re.findall(r"\d[\d,]*\.?\d*", s)}
    return {n for n in found if len(n) >= 2}


def support(unit, source):
    """Share of the unit's content words (4-letter stems) that occur in `source` (0..1)."""
    u = _stems(unit)
    return len(u & _stems(source)) / len(u) if u else 1.0


def _concrete(text):
    """Words that carry specifics: capitalised mid-sentence, or containing digits/symbols."""
    ws = text.split()
    return sum(1 for i, w in enumerate(ws) if i and (w[:1].isupper() or re.search(r"[\d_/.$%-]", w)))


_CUE = re.compile(r"\b(correction|corrected|actually|misspoke|i was wrong|earlier|original(?:ly)?)\b", re.I)
_NEG = re.compile(r"\b(?:not|instead of|rather than)\s+(?:the\s+)?(\d[\d,]*(?:\.\d+)?)")


def _supersede(kept, dropped):
    """"The cluster had 8 nodes, not 6" (a unit that says it is a correction) retires an earlier
    unit that still states the corrected-away number, so the note never holds both."""
    out = list(kept)
    for j, u in enumerate(kept):
        if not _CUE.search(u["text"]):
            continue
        for n in _NEG.findall(u["text"]):
            old = re.compile(rf"(?<![\d.,]){re.escape(n)}(?![\d]|\.\d)")
            for v in kept[:j]:
                if v in out and old.search(v["text"]) and not _CUE.search(v["text"]):
                    out.remove(v)
                    dropped["superseded_by_correction"] = dropped.get("superseded_by_correction", 0) + 1
    return out


def verify(units, segments):
    """Keep units the source supports. -> (kept units, dropped reasons {reason: count}).

    Each kept unit gets `support` and `segment_idx` (the segment that best matches it, the
    citation target). Dropped: a number the source never contains, content words the source does
    not contain, commentary about the source with no specifics, promotional lines, duplicates."""
    source = "\n".join(s.text for s in segments)
    source_nums = _nums(source) | {_NUMWORDS[w] for w in _words(source) if w in _NUMWORDS}
    stems = [(s.idx, _stems(s.text)) for s in segments]
    kept, dropped, seen = [], {}, []

    def drop(why):
        dropped[why] = dropped.get(why, 0) + 1

    for u in units:
        text = u["text"].strip()
        if _nums(text) - source_nums:
            drop("unsupported_number")
        elif _META.search(text) and _concrete(text) < 2:
            drop("meta_commentary")
        elif _PROMO.search(text):
            drop("promo")
        elif (sup := support(text, source)) < 0.5:
            drop("unsupported_text")
        elif any(difflib.SequenceMatcher(None, text.casefold(), p).ratio() >= 0.9 for p in seen):
            drop("duplicate")
        else:
            seen.append(text.casefold())
            ust = _stems(text)
            idx = max(stems, key=lambda p: len(ust & p[1]), default=(None,))[0]
            kept.append({**u, "text": text, "support": round(sup, 2), "segment_idx": idx})
    return _supersede(kept, dropped), dropped


# ---------------------------------------------------------------------------------- mentions

_ID = re.compile(r"\b[a-z][a-z0-9]*(?:[-_][a-z0-9]+)+\b")
_SPAN = re.compile(r"\b[A-Z][A-Za-z0-9\-]+(?:\s+(?:of\s+)?[A-Z][A-Za-z0-9\-]+)+\b")
_CAPS = re.compile(r"\b(?:[A-Z]{2,}[a-z]*|[A-Z][a-z]+[A-Z]\w*)\b")


def mentions(source, model_names=()):
    """Every named thing worth finding later: regex finds from the source + model entities that
    literally occur in it (a hallucinated entity is dropped). Casefold-deduplicated."""
    fold = re.sub(r"\s+", " ", source).casefold()
    names = [*(m for rx in (_SPAN, _ID, _CAPS) for m in rx.findall(source)),
             *(n for n in model_names if isinstance(n, str) and
               re.sub(r"\s+", " ", n).strip().casefold() in fold)]
    out, seen = [], set()
    for n in names:
        n = n.strip(" ,.;:")
        if len(n) > 2 and n.casefold() not in seen and n.casefold() not in _STOP:
            seen.add(n.casefold())
            out.append(n)
    return out[:80]


# ---------------------------------------------------------------------------------- compose

_GENERIC = _STOP | set("saved save mentioned middle want need remember video article note "
                       "thing stuff".split())
_LIST = re.compile(r"(\d+\.|-) ")


def intent_keywords(intent):
    """Stems of the content words of the user's stated reason."""
    return {w[:4] for w in _words(intent or "") if w not in _GENERIC and len(w) > 2}


_CODEY = re.compile(r"[{};=$<>\\]|^\s{2,}\S|^\S+\s+\S+=\S")


def code_blocks(segments, cap=3000):
    """Source passages that are code or configuration, kept verbatim: a model paraphrases them
    into prose and loses the exact names and values the note exists to preserve."""
    out, size = [], 0
    for s in segments:
        lines = [x for x in s.text.splitlines() if x.strip()]
        if s.locator == "description" or len(lines) < 3 or size + len(s.text) > cap:
            continue
        if sum(bool(_CODEY.search(x)) for x in lines) / len(lines) >= 0.5:
            out.append(s.text.strip())
            size += len(s.text)
    return out


def compose(context, units, intent, gaps, limits, code=()):
    """Markdown note from verified units. Only non-empty groups get a heading; the layout follows
    what the units are (numbered steps, facts, claims...), not the source's file type."""
    kw = intent_keywords(intent)
    need = 2 if len(kw) >= 3 else 1
    focus = [u for u in units if kw and len(kw & _stems(u["text"])) >= need]
    rest = [u for u in units if u not in focus]
    lines = []
    if intent:
        lines.append(f"**Why saved:** {intent.strip()}")
    if context:
        lines.append(context.strip())

    def block(us, head=None):
        types = {u["type"] for u in us}
        sectioned = len(types) > 1 and len(us) > 4
        if head and not sectioned:
            lines.append(f"## {head}")
        if types == {"step"}:
            lines.extend(f"{i}. {u['text']}" for i, u in enumerate(us, 1))
        elif not sectioned:
            lines.extend(f"- {u['text']}" for u in us)
        else:
            for t, h in HEADINGS.items():
                if grp := [u for u in us if u["type"] == t]:
                    block(grp, h)

    if focus:
        block(focus, "Relevant to why you saved this")
    if rest:
        block(rest, "Also in the source" if focus else None)
    for text in code:
        lines.append("## Source text, exact\n```\n" + text + "\n```")
    if gaps or limits:
        lines.append("**Limits:** " + " ".join(g.rstrip(".") + "." for g in [*gaps, *limits]))
    out = lines[0]
    for prev, ln in zip(lines, lines[1:]):
        out += ("\n" if _LIST.match(ln) and _LIST.match(prev) else "\n\n") + ln
    return out


# ---------------------------------------------------------------------------------- pipeline

def _norm_unit(u):
    t = str(u.get("type", "fact")).strip().lower()
    t = _SYN.get(t, t)
    text = numerals(str(u.get("text", "")).strip())
    first = text.split(" ", 1)[0]
    if first.isalpha() and " -" not in text and len(text.split()) > 3:  # commands keep their case
        text = text[0].upper() + text[1:]
    return {"type": t if t in HEADINGS else "fact", "text": text}


def _labelled(segs):
    """Source text as the model sees it: the author's description is labelled apart."""
    d = "\n".join(s.text for s in segs if s.locator == "description")
    b = "\n\n".join(s.text for s in segs if s.locator != "description")
    return (f"DESCRIPTION:\n{d}\n\n" if d else "") + (f"TRANSCRIPT/TEXT:\n{b}" if b else "")


_THIS = re.compile(r"^(this|the) (source|video|reel|article|text|podcast|episode|talk|clip|post)\b"
                   r"( is| describes| provides| covers| lists| shows| contains| presents)?"
                   r"( an?| the)? ", re.I)
_PROMISE = re.compile(r"\b(\d+|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\s+"
                      r"(?:[\w-]+\s+){0,2}(habits|tips|steps|ways|mistakes|reasons|rules|lessons|"
                      r"tools|things|ideas|secrets|strategies|hacks|books|points|questions)\b", re.I)


def _clean_context(ctx):
    """Context line without 'This source is...' lead-ins and without commentary."""
    ctx = _THIS.sub("", ctx.strip())
    ctx = ctx[:1].upper() + ctx[1:]
    return "" if len(ctx.split()) < 3 or (_META.search(ctx) and _concrete(ctx) < 2) else ctx


class _Run:  # pylint: disable=too-few-public-methods  # call accounting for one source
    def __init__(self):
        self.calls, self.chars, self.t0, self.res = 0, 0, time.monotonic(), None

    def ask(self, backend, system, user):
        """One extraction call (+ at most one repair retry inside _ask)."""
        self.calls += 1
        self.chars += len(system) + len(user)
        obj, res = _ask(backend, _msgs(system, user), SCHEMA)
        self.res = res or self.res
        return obj


def _extract_all(run, backend, system, segs):
    """Unit objects from every batch (the map phase keeps units, never summaries). None if a
    batch fails."""
    desc = [s for s in segs if s.locator == "description"]
    body = [s for s in segs if s.locator != "description"]
    budget = (backend.capabilities.context_window * _CHARS_PER_TOKEN - _OVERHEAD - len(system)
              - sum(len(s.text) for s in desc))
    objs = []
    for batch in _batches(body, max(500, budget)):
        obj = run.ask(backend, system, _labelled([*desc, *batch]))
        if obj is None:
            return None
        objs.append(obj)
    if not body and (obj := run.ask(backend, system, _labelled(desc))):
        objs.append(obj)
    return objs or None


def _focus_pass(run, backend, segs, intent, kw):
    """Intent present but no unit touches it: re-extract from the best-matching segments only."""
    scored = sorted(((len(kw & _stems(s.text)), s) for s in segs if s.locator != "description"),
                    key=lambda p: -p[0])
    top = [s for n, s in scored[:2] if n]
    if not top:
        return []
    obj = run.ask(backend, PROMPT.format(intent=_INTENT_ONLY.format(intent)), _labelled(top))
    return [_norm_unit(u) for u in (obj or {}).get("units", [])]


def build(registry, segments, *, title="", intent=None, limits=(), kind=""):
    """(candidates, "backend:model") for one source, or None when no model backend can run
    (the caller falls back to the legacy distiller).

    `intent` is the user's own words (explicit) or None (unknown); it is never invented here."""
    backends = [b for b in registry.chain("distill") if getattr(b, "type", "") != "heuristic"]
    if not backends:
        return None
    body = "\n".join(s.text for s in segments if s.locator != "description")
    if kind == "note" and len(segments) == 1 and len(body) < 400 and "\n\n" not in body:
        # already a short note: keep it as it is, no model call and nothing leaves the machine
        unit = {"type": "fact", "text": body.strip(), "support": 1.0,
                "segment_idx": segments[0].idx}
        return _candidates(title, body.strip(), [unit], intent, [], list(limits), {}, [],
                           {"calls": 0, "verbatim": True}, "verbatim")
    segs, repairs = repair_terms(segments, title)
    kw = intent_keywords(intent)
    system = PROMPT.format(intent=_INTENT.format(intent) if intent else "")
    for backend in backends:
        run, lim = _Run(), list(limits)
        try:
            objs = _extract_all(run, backend, system, segs)
            if objs is None:
                continue
            raw = [_norm_unit(u) for o in objs for u in o.get("units", [])]
            kept, dropped = verify([u for u in raw if u["text"]], segs)
            if kw and not any(kw & _stems(u["text"]) for u in kept):
                extra, _ = verify(_focus_pass(run, backend, segs, intent, kw), segs)
                have = {k["text"].casefold() for k in kept}
                kept += [{**u, "focus": True} for u in extra if u["text"].casefold() not in have]
                if not extra:
                    lim.append(f"Nothing in the source matched your reason for saving "
                               f"({intent.strip()})")
        except ProviderError:
            continue
        if not kept:
            continue
        ctx = _clean_context(objs[0].get("context") or "")
        # a gap is believable only when the source itself promises a counted list ("10 habits");
        # models invent "not provided" noise otherwise
        promised = _PROMISE.search("\n".join(s.text for s in segs))
        gaps = [g.strip() for o in objs for g in o.get("gaps", []) if isinstance(g, str)
                and g.strip()] if promised else []
        names = [n for o in objs for n in o.get("entities", [])]
        stats = {"calls": run.calls, "prompt_chars": run.chars, "raw_units": len(raw),
                 "seconds": round(time.monotonic() - run.t0, 1)}
        return _candidates(title, compose(ctx, kept, intent, gaps, lim, code_blocks(segments)),
                           kept, intent, gaps, lim,
                           dropped, repairs, stats, f"{run.res.backend}:{run.res.model}",
                           mentions("\n".join(s.text for s in segments), names), ctx)
    return None


def _candidates(title, md, units, intent, gaps, limits, dropped, repairs, stats, by,
                names=(), context=""):
    data = {"version": VERSION, "context": context,
            "intent": {"state": "explicit" if intent else "unknown", "text": intent or None},
            "units": [{k: u.get(k) for k in ("type", "text", "support", "segment_idx", "focus")}
                      for u in units],
            "gaps": gaps, "limits": limits, "dropped": dropped,
            "repairs": [{"heard": a, "term": b} for a, b in repairs], "stats": stats}
    out = [Candidate(kind="note", title=title or "", body=md, data=data, entities=list(names))]
    if names:
        out.append(Candidate(kind="mentions", title=f"Mentioned in {title or 'this source'}",
                             body=", ".join(names), entities=list(names)))
    if not stats.get("verbatim"):
        out += [Candidate(kind="unit", title=u["text"][:80], body=u["text"],
                          data={"type": u["type"], "support": u.get("support")},
                          segment_idx=u.get("segment_idx")) for u in units]
    return out, by
