"""Note-quality benchmark: legacy summary+insights distiller vs the knowledge-note pipeline.

    uv run python eval/notes/run_notes_eval.py --pipeline legacy --think      # baseline as shipped
    uv run python eval/notes/run_notes_eval.py --pipeline legacy               # legacy, thinking off
    uv run python eval/notes/run_notes_eval.py --pipeline note                 # new pipeline
    options: --model gemma4:e4b  --cases twitch_reel,plain_note  --ctx 8192

Needs a running Ollama with the model already pulled; talks to nothing else. Scoring is deterministic
(no LLM judge): required-term recall, forbidden strings, commentary phrases, numbers that occur in
no source text, length, model calls and latency. A case is BLOCKING when a critical required term is
missing, a forbidden string appears, a number is invented, or a promised-but-missing list is not
flagged. Results go to eval/notes/results/ (json + markdown with the generated notes).
"""
import argparse
import datetime
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parents[1] / "src"))

# pylint: disable=wrong-import-position
from infoparser.domain.models import SegmentIn  # noqa: E402
from infoparser.pipeline import note as note_mod  # noqa: E402
from infoparser.pipeline import distill as distill_mod  # noqa: E402
from infoparser.pipeline.distill import distill  # noqa: E402
from infoparser.pipeline.runner import profile_of  # noqa: E402
from infoparser.providers.registry import Registry, _build  # noqa: E402

COMMENTARY = re.compile(
    r"\b(the )?(video|creator|author|speaker|article|podcast|presenter|source|text|tutorial)\b"
    r"[^.\n]{0,40}\b(discuss|explain|provid|outlin|cover|explor|offer|describ|present|emphasi|"
    r"encourag|highlight|walks?|shares?|talks?|goes over|dives?)\w*|actionable|insightful|"
    r"comprehensive|valuable|roadmap for", re.I)
GAP = re.compile(r"\b(only|not (provided|given|listed|stated)|remaining|rest of|missing|incomplete|"
                 r"limits)\b", re.I)
NUMWORDS = dict(zip("zero one two three four five six seven eight nine ten eleven twelve".split(),
                    map(str, range(13))))


def ollama_base():
    """Ollama URL (OLLAMA_HOST honoured)."""
    raw = os.environ.get("OLLAMA_HOST") or "127.0.0.1:11434"
    return (raw if "://" in raw else "http://" + raw).replace("//0.0.0.0", "//127.0.0.1")


class Counting:  # pylint: disable=too-few-public-methods  # counts calls and seconds of generate()
    """Delegating proxy around a backend."""

    def __init__(self, inner):
        self.inner, self.calls, self.secs = inner, 0, 0.0

    def __getattr__(self, k):
        return getattr(self.inner, k)

    def generate(self, *a, **kw):
        """Count and time the call."""
        t0 = time.monotonic()
        try:
            return self.inner.generate(*a, **kw)
        finally:
            self.calls += 1
            self.secs += time.monotonic() - t0


def make_registry(model, think, ctx):
    """One Ollama backend (+ heuristic, always last) -> (Registry, counting proxy)."""
    spec = {"type": "openai_compat", "base_url": ollama_base() + "/v1", "model": model,
            "timeout": 600, "context_window": ctx}
    if not think:
        spec |= {"think": False, "num_ctx": ctx}
    proxy = Counting(_build("ollama", spec))
    h = _build("h", {"type": "heuristic"})
    return Registry({"ollama": proxy, "h": h}, {}, {"distill": ["ollama"]}, False), proxy


def segments_of(case):
    """Same layout the runner builds: description first (locator 'description'), then the body."""
    segs = [(case["description"], "description")] if case.get("description") else []
    segs += [(t, loc) for loc, t in case["segments"]]
    return [SegmentIn(i, t, loc) for i, (t, loc) in enumerate(segs)]


def run_legacy(reg, case, segs):
    """Existing pipeline output rendered as the user sees it: summary then insights."""
    cands, by = distill(reg, segs, profile=profile_of(case["kind"], case.get("intent")),
                        title=case["title"] or "", user_context=case.get("intent"))
    text = "\n".join(c.body for c in cands)
    return {"note": text, "index": text + " " + " ".join(e for c in cands for e in c.entities),
            "by": by, "gaps": []}


def run_note(reg, case, segs):
    """New pipeline: the note body, plus the mention index for index_only checks."""
    res = note_mod.build(reg, segs, title=case["title"] or "", intent=case.get("intent"),
                         kind=case["kind"])
    if res is None:
        return {"note": "", "index": "", "by": "none", "gaps": [], "error": "no result"}
    cands, by = res
    note = next(c for c in cands if c.kind == "note")
    index = " ".join(c.body for c in cands if c.kind in ("note", "mentions"))
    return {"note": note.body, "index": index, "by": by, "gaps": note.data["gaps"],
            "data": note.data}


def _nums(s):
    found = {m.rstrip(".").replace(",", "") for m in re.findall(r"\d[\d,]*\.?\d*", s)}
    return {n for n in found if len(n) >= 2 or "." in n}


def score(case, out, secs, calls):
    """Deterministic scores for one generated note."""
    note, idx = out["note"].casefold(), out["index"].casefold()

    def hit(group, text):
        for alt in group["any"]:
            alt = alt.casefold()
            if (re.search(rf"\b{re.escape(alt)}\b", text) if group.get("word") else alt in text):
                return True
        return False

    groups = case["must"]
    ok = [hit(g, idx if g.get("index_only") else note) for g in groups]
    source = " ".join([case.get("description") or "", *[t for _, t in case["segments"]]])
    src_words = re.findall(r"[a-z]+", source.casefold())
    src_nums = _nums(source) | {NUMWORDS[w] for w in src_words if w in NUMWORDS}
    invented = sorted(_nums(out["note"]) - src_nums)
    forbidden = [f for f in case["must_not"] if f.casefold() in note]
    crit_missing = [g["any"][0] for g, o in zip(groups, ok) if not o and g.get("critical")]
    words = len(out["note"].split())
    gap_ok = (not case.get("expect_gap")) or bool(GAP.search(out["note"]) or out["gaps"])
    too_long = bool(case.get("max_words")) and words > case["max_words"]
    blocking = bool(crit_missing or forbidden or invented or not gap_ok or too_long)
    return {"recall": round(sum(ok) / len(ok), 2), "critical_missing": crit_missing,
            "forbidden_hit": forbidden, "invented_numbers": invented,
            "commentary": len(COMMENTARY.findall(out["note"])), "words": words,
            "gap_flagged": gap_ok, "too_long": too_long, "blocking": blocking,
            "seconds": round(secs, 1), "calls": calls}


def main():
    """Run the selected cases and write results/<date>-<model>-<variant>.{json,md}."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--pipeline", choices=("legacy", "note"), required=True)
    ap.add_argument("--model", default="gemma4:e4b")
    ap.add_argument("--think", action="store_true", help="leave thinking on (/v1 as shipped)")
    ap.add_argument("--ctx", type=int, default=8192)
    ap.add_argument("--head-prompt", action="store_true",
                    help="legacy only: the system prompt as committed at HEAD (before the WIP edit)")
    ap.add_argument("--cases", default="")
    ap.add_argument("--tag", default="")
    a = ap.parse_args()
    cases = json.loads((ROOT / "cases.json").read_text())["cases"]
    if a.cases:
        cases = [c for c in cases if c["id"] in a.cases.split(",")]
    if a.head_prompt:
        distill_mod.system_prompt = lambda profile, title, user_context: (
            f"You distill a source titled {title!r} into knowledge items (profile: {profile}). "
            f"User context: {user_context or 'none'}. Only state what the text says; quotes "
            "must be copied verbatim from the text. Reply with ONLY JSON matching the given schema.")
    reg, proxy = make_registry(a.model, a.think, a.ctx)
    run = run_legacy if a.pipeline == "legacy" else run_note
    rows = []
    for case in cases:
        proxy.calls, proxy.secs = 0, 0.0
        t0 = time.monotonic()
        try:
            out = run(reg, case, segments_of(case))
        except Exception as e:  # pylint: disable=broad-exception-caught  # record, keep going
            out = {"note": "", "index": "", "by": "error", "gaps": [], "error": repr(e)}
        secs = time.monotonic() - t0
        row = {"id": case["id"], "output": out, **score(case, out, secs, proxy.calls)}
        rows.append(row)
        print(f"{case['id']:34} recall={row['recall']:.2f} block={row['blocking']!s:5} "
              f"commentary={row['commentary']} words={row['words']:4} calls={row['calls']} "
              f"{row['seconds']}s", flush=True)
    variant = (f"{a.pipeline}{'-headprompt' if a.head_prompt else ''}-"
               f"{'think' if a.think else 'nothink'}{('-' + a.tag) if a.tag else ''}")
    outdir = ROOT / "results"
    outdir.mkdir(exist_ok=True)
    base = outdir / f"{datetime.date.today().isoformat()}-{a.model.replace(':', '-')}-{variant}"
    n = len(rows)
    summary = {"variant": variant, "model": a.model, "cases": n,
               "mean_recall": round(sum(r["recall"] for r in rows) / n, 3),
               "blocking": sum(r["blocking"] for r in rows),
               "commentary_total": sum(r["commentary"] for r in rows),
               "invented_number_cases": sum(bool(r["invented_numbers"]) for r in rows),
               "mean_words": round(sum(r["words"] for r in rows) / n),
               "total_calls": sum(r["calls"] for r in rows),
               "total_seconds": round(sum(r["seconds"] for r in rows), 1)}
    base.with_suffix(".json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=1))
    md = [f"# {variant} ({a.model})", "", "```json", json.dumps(summary, indent=1), "```", ""]
    for r in rows:
        md += [f"## {r['id']}  recall {r['recall']}  blocking={r['blocking']}  "
               f"{r['seconds']}s / {r['calls']} calls",
               f"missing(critical)={r['critical_missing']} forbidden={r['forbidden_hit']} "
               f"invented={r['invented_numbers']} commentary={r['commentary']}", "",
               r["output"]["note"] or f"(no output: {r['output'].get('error')})", ""]
    base.with_suffix(".md").write_text("\n".join(md))
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
