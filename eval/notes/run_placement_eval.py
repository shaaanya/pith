"""Shelf-placement benchmark: rules vs model vs model with a rule hint, on labelled notes.

    uv run python eval/notes/run_placement_eval.py --model gemma4:e4b
    options: --cases-file eval/notes/placement_cases.json  --ctx 8192  --think

Strategies: A rules only; B model only (unknown answer -> rules); C model given the rule's suggestion;
D C, but when the model says "other" and a rule matched, the rule wins. Accuracy = exact shelf match.
Needs a running Ollama with the model pulled. Results go to eval/notes/results/ (json + markdown).
"""
import argparse
import collections
import datetime
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parents[1] / "src"))
sys.path.insert(0, str(ROOT))

# pylint: disable=wrong-import-position
from run_notes_eval import make_registry  # noqa: E402
from pith.pipeline import place  # noqa: E402
from pith.store.shelves import list_shelves  # noqa: E402
from pith.store.db import connect, migrate  # noqa: E402


def shelves_list():
    """The seeded built-in shelves, read from a throwaway migrated database."""
    conn = connect(":memory:")
    migrate(conn)
    return list_shelves(conn)


def run(model, ctx, think, cases, shelves):
    reg, proxy = make_registry(model, think, ctx)
    backend = proxy
    rows = []
    for c in cases:
        r_shelf, r_by, _ = place.rules(c["intent"], c["host"], bool(c["body"]))
        hint = r_shelf if r_by == "rule" else None
        calls0, t0 = proxy.calls, proxy.secs
        b = place.ask(backend, c["title"], c["body"], c["intent"], c["host"], shelves)
        cc = place.ask(backend, c["title"], c["body"], c["intent"], c["host"], shelves, hint=hint)
        pick_b = b[0] if b else r_shelf
        pick_c = cc[0] if cc else r_shelf
        pick_d = r_shelf if (pick_c == "other" and r_by == "rule") else pick_c
        rows.append({"title": c["title"], "expected": c["expected"], "note": c.get("note", ""),
                     "A": r_shelf, "B": pick_b, "C": pick_c, "D": pick_d,
                     "B_raw": b, "C_raw": cc, "calls": proxy.calls - calls0,
                     "secs": round(proxy.secs - t0, 1)})
    return rows


def report(rows, model):
    out = [f"# Placement benchmark: {model}\n", f"{len(rows)} labelled notes\n",
           "| strategy | correct | accuracy |", "|---|---|---|"]
    for k, label in (("A", "rules only"), ("B", "model only"), ("C", "model + rule hint"),
                     ("D", "C, rule beats model 'other'")):
        n = sum(r[k] == r["expected"] for r in rows)
        out.append(f"| {k} {label} | {n}/{len(rows)} | {n / len(rows):.0%} |")
    out.append(f"\nmodel seconds per note: {sum(r['secs'] for r in rows) / len(rows):.1f} "
               f"({sum(r['calls'] for r in rows)} calls)\n")
    for k in "ABCD":
        conf = collections.Counter((r["expected"], r[k]) for r in rows if r[k] != r["expected"])
        out.append(f"\nStrategy {k} misses: " + (", ".join(
            f"{e}->{g} x{n}" for (e, g), n in conf.most_common()) or "none"))
    out.append("\n## Per note (expected | A B C D)\n")
    for r in rows:
        flag = "" if r["D"] == r["expected"] else "  <-- D wrong"
        out.append(f"- {r['title']}: {r['expected']} | {r['A']} {r['B']} {r['C']} {r['D']}{flag}")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="gemma4:e4b")
    ap.add_argument("--ctx", type=int, default=8192)
    ap.add_argument("--think", action="store_true")
    ap.add_argument("--cases-file", default=str(ROOT / "placement_cases.json"))
    ap.add_argument("--tag", default="")
    a = ap.parse_args()
    cases = json.loads(Path(a.cases_file).read_text())
    rows = run(a.model, a.ctx, a.think, cases, shelves_list())
    stem = (f"{datetime.date.today()}-placement-{a.model.replace(':', '-')}"
            f"{'-' + a.tag if a.tag else ''}")
    res = ROOT / "results"
    res.mkdir(exist_ok=True)
    (res / f"{stem}.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False))
    md = report(rows, a.model)
    (res / f"{stem}.md").write_text(md)
    print(md)


if __name__ == "__main__":
    main()
