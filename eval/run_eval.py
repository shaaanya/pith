"""Reproducible evaluation of InfoParser retrieval, dedupe and extraction with REAL local models.

Needs a running Ollama (127.0.0.1:11434 or OLLAMA_HOST) with the chat and embedding models already
pulled; it never pulls anything and never touches the network beyond that server. Product code and
defaults are used as shipped (dedupe 0.92/0.75, no embedding prefixes); this script only MEASURES.
Prefixes are applied inside the harness only. Run from the repo root:

    uv run python eval/run_eval.py [--runs 5] [--chat qwen2.5:0.5b] [--embed nomic-embed-text]

Everything runs in a temporary home (never ~/InfoParser; checked on exit). Writes
eval/results/<UTC date>-<chat model>.json and a .md summary next to it.
"""
import argparse
import datetime
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import numpy as np

import metrics
from infoparser.config import load_config
from infoparser.domain.models import SegmentIn
from infoparser.pipeline import runner
from infoparser.pipeline.chunk import chunk_text
from infoparser.pipeline import distill as distill_mod
from infoparser.pipeline.schemas import SCHEMAS, validate
from infoparser.providers.registry import Registry
from infoparser.retrieval import vectors
from infoparser.retrieval.search import search
from infoparser.services import build

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
KS = (1, 3, 5, 10)
CATEGORIES = ("keyword", "entity", "numeric", "paraphrase")
QUERY_PREFIX, DOC_PREFIX = "search_query: ", "search_document: "
SEED = 20260611  # bootstrap seed; the models' own sampling is not configurable (see docs)


def ollama_base():
    """Ollama server URL (OLLAMA_HOST honoured, default 127.0.0.1:11434)."""
    raw = os.environ.get("OLLAMA_HOST") or "127.0.0.1:11434"
    return (raw if "://" in raw else "http://" + raw).replace("//0.0.0.0", "//127.0.0.1")


def _get_json(url):
    with urllib.request.urlopen(url, timeout=10) as resp:  # loopback Ollama only
        return json.load(resp)


def environment(chat, embed):
    """Versions and model digests (from the running server) for the results file."""
    base = ollama_base()
    tags = {m["name"]: m for m in _get_json(base + "/api/tags")["models"]}
    digests = {}
    for name in (chat, embed):
        m = tags.get(name) or tags.get(name + ":latest")
        if m is None:
            sys.exit(f"model {name!r} is not installed in Ollama (installed: {sorted(tags)})")
        digests[name] = {"digest": m["digest"], "size_bytes": m["size"]}
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                          text=True, check=False).stdout.strip()
    return {"ollama_version": _get_json(base + "/api/version")["version"], "models": digests,
            "python": platform.python_version(), "numpy": np.__version__,
            "platform": platform.platform(), "git_head": head, "ollama_url": base,
            "chat_temperature": "not set by InfoParser (Ollama/model default); not configurable"}


def make_cfg(home, chat, embed, *, route):
    """Config for one openai_compat backend against local Ollama, plus the heuristic backend."""
    cfg = load_config(env={"INFOPARSER_HOME": str(home)})
    cfg.backends = {"ollama": {"type": "openai_compat", "base_url": ollama_base() + "/v1",
                               "model": chat, "embed_model": embed, "timeout": 120},
                    "h": {"type": "heuristic"}}
    cfg.tasks = route
    return cfg


class TimedEmbedder:  # pylint: disable=too-few-public-methods  # the Embedder port has one method
    """Wraps the real embedder: optional task prefix (harness-only) and a per-call latency log."""

    locality = "local"

    def __init__(self, inner):
        self.inner, self.prefix, self.log = inner, "", []
        self.name, self.capabilities = inner.name, inner.capabilities

    def embed(self, texts):
        """Embed with the current prefix; record (n_texts, seconds)."""
        t0 = time.perf_counter()
        res = self.inner.embed([self.prefix + t for t in texts])
        self.log.append((len(texts), time.perf_counter() - t0))
        return res


def _route_embedder(svc, emb):
    orig = svc.registry.first
    svc.registry.first = lambda task: emb if task == "embed" else orig(task)


def _doc_of_source(conn):
    return {r["source_id"]: r["original_filename"].rsplit(".", 1)[0] for r in conn.execute(
        "SELECT source_id, original_filename FROM inbox_items WHERE source_id IS NOT NULL")}


def ingest(home, docs, chat, embed, prefix):
    """Real pipeline (heuristic distill, real embeddings) over every doc -> (svc, embedder)."""
    cfg = make_cfg(home, chat, embed, route={"distill": ["h"], "embed": ["ollama"]})
    svc = build(cfg)
    emb = TimedEmbedder(svc.registry.first("embed"))
    emb.prefix = DOC_PREFIX if prefix else ""
    _route_embedder(svc, emb)
    for doc_id, text in docs:
        runner.process(svc, svc.inbox.submit(adapter="eval", file=text.encode(),
                                             filename=f"{doc_id}.md").id)
    errs = svc.conn.execute("SELECT stage, detail FROM processing_events WHERE status='error'")
    errs = [tuple(r) for r in errs]
    if errs:
        sys.exit(f"pipeline errors during ingest: {errs[:3]}")
    return svc, emb


def _rank_vector(svc, emb, q, doc_of):
    """Doc ids ranked by best cosine over item and segment vectors (what the vector leg sees)."""
    res = emb.embed([q])
    hits = []
    for kind, table in (("item", "knowledge_items"), ("segment", "segments")):
        for oid, score in vectors.cosine_topk(svc.conn, res.model_id, res.vectors[0], 50, kind):
            row = svc.conn.execute(f"SELECT source_id FROM {table} WHERE id=?", (oid,)).fetchone()
            hits.append((score, doc_of[row["source_id"]]))
    return metrics.unique(d for _, d in sorted(hits, key=lambda h: -h[0]))


def _rank_search(svc, q, mode, doc_of):
    return metrics.unique(doc_of[h.source_id] for h in search(svc, q, limit=40, mode=mode))


def score_rows(rankings, queries):
    """Per category and overall: recall@k, MRR, Wilson interval on recall@5."""
    out = {}
    for cat in (*CATEGORIES, "all"):
        sel = [(r, q) for r, q in zip(rankings, queries) if cat in ("all", q["category"])]
        row = {"n": len(sel)}
        for k in KS:
            row[f"recall@{k}"] = sum(metrics.recall_at_k(metrics.unique(r)[:10], q["relevant"], k)
                                     for r, q in sel) / len(sel)
        row["mrr"] = sum(metrics.reciprocal_rank(r[:10], q["relevant"]) for r, q in sel) / len(sel)
        hits5 = sum(metrics.recall_at_k(r, q["relevant"], 5) == 1 for r, q in sel)
        row["recall@5_wilson95"] = metrics.wilson(hits5, len(sel))
        out[cat] = row
    return out


def retrieval_phase(tmp, data, chat, embed):  # pylint: disable=too-many-locals  # linear phase
    """FTS vs vector-only vs hybrid, with and without harness-side nomic prefixes."""
    docs, queries = data["docs"], data["queries"]
    results, latency = {}, {}
    for variant, prefix in (("plain", False), ("prefixed", True)):
        svc, emb = ingest(Path(tmp) / f"home-{variant}", docs, chat, embed, prefix)
        doc_of = _doc_of_source(svc.conn)
        assert len(doc_of) == len(docs), (len(doc_of), len(docs))
        ingest_log = list(emb.log)
        emb.log.clear()
        emb.prefix = QUERY_PREFIX if prefix else ""
        ranks = {"vector": [_rank_vector(svc, emb, q["q"], doc_of) for q in queries]}
        qlog = [s for n, s in emb.log if n == 1]
        ranks["hybrid"] = [_rank_search(svc, q["q"], "hybrid", doc_of) for q in queries]
        ranks["fts"] = [_rank_search(svc, q["q"], "fts", doc_of) for q in queries]
        for mode, rk in ranks.items():
            if mode != "fts" or not prefix:  # FTS never sees the embedder: one row
                results[f"{mode}-{variant}" if mode != "fts" else "fts"] = score_rows(rk, queries)
        results[f"_rankings-{variant}"] = ranks
        latency[variant] = {
            "ingest_batches": [{"texts": n, "seconds": round(s, 4)} for n, s in ingest_log],
            "first_call_seconds": round(ingest_log[0][1], 4),
            "query_single_text_seconds": metrics.summarize(qlog),
            "query_p95_seconds": sorted(qlog)[int(0.95 * len(qlog)) - 1]}
        svc.conn.close()
    rankings = {k: v for k, v in results.items() if k.startswith("_rankings")}
    return {k: v for k, v in results.items() if k not in rankings}, latency, rankings


def _embed_all(chat, embed, texts, prefix):
    cfg = make_cfg(tempfile.gettempdir(), chat, embed, route={})
    reg = Registry.from_config(cfg)
    backend = reg.backends["ollama"]
    uniq = sorted(set(texts))
    vecs = {}
    for i in range(0, len(uniq), 16):
        part = uniq[i:i + 16]
        for t, v in zip(part, backend.embed([prefix + t for t in part]).vectors):
            vecs[t] = np.asarray(v, dtype=np.float32) / np.linalg.norm(v)
    return vecs


def dedupe_phase(pairs, chat, embed):  # pylint: disable=too-many-locals  # linear phase
    """Cosine distribution per label and precision/recall of the shipped thresholds."""
    out = {}
    for variant, prefix in (("plain", ""), ("prefixed", DOC_PREFIX)):
        vecs = _embed_all(chat, embed, [t for p in pairs for t in (p["a"], p["b"])], prefix)
        scores = [float(vecs[p["a"]] @ vecs[p["b"]]) for p in pairs]
        labels = [p["label"] for p in pairs]
        dup, rel = [lb == "duplicate" for lb in labels], [lb == "related" for lb in labels]
        link = [d or r for d, r in zip(dup, rel)]
        by = {lb: [s for s, x in zip(scores, labels) if x == lb] for lb in set(labels)}
        kinds = {k: [s for s, p in zip(scores, pairs) if p.get("kind") == k]
                 for k in ("reworded", "boilerplate")}
        sweep = []
        for i in range(50, 100):
            t = i / 100
            p, r = metrics.precision_recall(scores, dup, t)
            sweep.append({"threshold": t, "dup_precision": p, "dup_recall": r,
                          "dup_f1": (2 * p * r / (p + r)) if p and r else 0.0})
        out[variant] = {
            "class_stats": {lb: metrics.summarize(v) for lb, v in by.items()},
            "duplicate_by_kind": {k: metrics.summarize(v) for k, v in kinds.items()},
            "dup@0.92": dict(zip(("precision", "recall"),
                                 metrics.precision_recall(scores, dup, 0.92))),
            "related_band[0.75,0.92)": dict(zip(
                ("precision", "recall"), metrics.precision_recall(scores, rel, 0.75, upper=0.92))),
            "linked@0.75 (dup or related)": dict(zip(
                ("precision", "recall"), metrics.precision_recall(scores, link, 0.75))),
            "n_pairs": len(pairs), "sweep": sweep, "scores": scores}
    return out


def _wrap_calls(backend):
    """Log every generate() call of the real backend: seconds and whether it raised."""
    real, calls = backend.generate, []

    def gen(messages, **kw):
        t0, call = time.perf_counter(), {"error": True, "seconds": 0.0}
        calls.append(call)
        try:
            res = real(messages, **kw)
            call["error"], call["text"] = False, res.text
            return res
        finally:
            call["seconds"] = time.perf_counter() - t0

    backend.generate = gen
    return calls


def _reason(text):
    """Why a model reply fails the generic schema (the product's own parse and validator)."""
    obj = distill_mod._parse(text)  # pylint: disable=protected-access  # measure the product parse
    return "not valid JSON" if obj is None else validate(obj, SCHEMAS["generic"]) or "valid"


def _texts(cands):
    return [f"{c.title}\n{c.body}\n{c.evidence or ''}" for c in cands]


def _facts(doc, cands):
    items = _texts(cands)
    exact = [metrics.fact_found(f, items) for f in doc["facts"]]
    loose = [metrics.fact_found(f, items, loose=True) for f in doc["facts"]]
    return sum(exact) / len(exact), sum(loose) / len(loose)


def _one_run(reg, doc, calls):
    calls.clear()
    segs = [SegmentIn(i, t, loc) for i, (t, loc) in enumerate(chunk_text(doc["text"]))]
    t0 = time.perf_counter()
    cands, by = distill_mod.distill(reg, segs, profile="generic", title=doc["title"],
                                    user_context="")
    exact, loose = _facts(doc, cands)
    n = len(calls)
    model_made = by.startswith("ollama:")
    outcome = ("first_try" if model_made and n == 1 else "repaired" if model_made
               else "fallback_error" if any(c["error"] for c in calls) else "fallback_invalid")
    return {"doc": doc["id"], "by": by, "model_made": model_made, "model_calls": n,
            "outcome": outcome, "reasons": [_reason(c["text"]) for c in calls if "text" in c],
            "items": len(cands),
            "stated": sum(c.provenance == "stated" for c in cands),
            "fact_recall_exact": exact, "fact_recall_loose": loose,
            "seconds": round(time.perf_counter() - t0, 3)}


def _rate(k, n):
    return {"k": k, "n": n, "rate": k / n if n else None, "wilson95": metrics.wilson(k, n)}


def _mean_by_doc(runs, key):
    """Mean of `key` per doc, then the mean over docs, with a doc-level bootstrap interval."""
    per = {}
    for r in runs:
        per.setdefault(r["doc"], []).append(r[key])
    vals = [sum(v) / len(v) for v in per.values()]
    return {"mean": sum(vals) / len(vals) if vals else None, "n_runs": len(runs),
            "n_docs": len(vals), "bootstrap95_over_docs": metrics.bootstrap_ci(vals, seed=SEED)}


def extraction_phase(docs, chat, embed, n_runs):  # pylint: disable=too-many-locals  # linear phase
    """N runs per doc through the real distill chain (model, then heuristic) and heuristic-only."""
    cfg = make_cfg(tempfile.gettempdir(), chat, embed, route={"distill": ["ollama"]})
    reg = Registry.from_config(cfg)
    calls = _wrap_calls(reg.backends["ollama"])
    runs = [{**_one_run(reg, d, calls), "run": i} for i in range(n_runs) for d in docs]
    heur = Registry.from_config(
        make_cfg(tempfile.gettempdir(), chat, embed, route={"distill": ["h"]}))
    heur_runs = [_one_run(heur, d, []) for d in docs]
    model_runs = [r for r in runs if r["model_made"]]
    fb_runs = [r for r in runs if not r["model_made"]]
    count = {o: sum(r["outcome"] == o for r in runs)
             for o in ("first_try", "repaired", "fallback_invalid", "fallback_error")}
    first_invalid = count["repaired"] + count["fallback_invalid"] + count["fallback_error"]
    summary = {
        "runs_total": len(runs), "n_docs": len(docs), "runs_per_doc": n_runs,
        "model_made": _rate(len(model_runs), len(runs)),
        "heuristic_fallback": _rate(len(fb_runs), len(runs)),
        "schema_valid_first_reply": _rate(count["first_try"], len(runs)),
        "schema_valid_after_repair": _rate(count["first_try"] + count["repaired"], len(runs)),
        "repair_attempted": _rate(first_invalid, len(runs)),
        "repair_succeeded_given_attempted": _rate(count["repaired"], first_invalid),
        "outcomes": count,
        "items_per_run": {"model": metrics.summarize([r["items"] for r in model_runs]),
                          "heuristic_in_chain": metrics.summarize([r["items"] for r in fb_runs])},
        "stated_fraction_model": (sum(r["stated"] for r in model_runs)
                                  / max(1, sum(r["items"] for r in model_runs))),
        "fact_recall": {
            "model_path": {k: _mean_by_doc(model_runs, k)
                           for k in ("fact_recall_exact", "fact_recall_loose")},
            "heuristic_fallback_runs_in_chain": {k: _mean_by_doc(fb_runs, k) if fb_runs else None
                                                 for k in ("fact_recall_exact",
                                                           "fact_recall_loose")},
            "heuristic_only_all_docs": {k: _mean_by_doc(heur_runs, k)
                                        for k in ("fact_recall_exact", "fact_recall_loose")},
            "as_shipped_chain_all_runs": {k: _mean_by_doc(runs, k)
                                          for k in ("fact_recall_exact", "fact_recall_loose")}},
        "model_seconds_per_run": metrics.summarize([r["seconds"] for r in runs]),
        "model_made_by_doc": {d["id"]: sum(r["model_made"] for r in runs if r["doc"] == d["id"])
                              for d in docs}}
    return {"summary": summary, "runs": runs, "heuristic_only_runs": heur_runs}


def _fmt(v, nd=3):
    return "n/a" if v is None else f"{v:.{nd}f}"


def _ci(pair):
    return f"[{pair[0]:.2f}, {pair[1]:.2f}]"


def markdown(res):
    """Compact human-readable summary of the results dict."""
    lines = [f"# Evaluation results {res['date']} ({res['chat_model']} + {res['embed_model']})", ""]
    lines += ["Environment: " + json.dumps(res["environment"]), "",
              f"## Retrieval (doc-level, n={res['dataset']['queries']} queries)", "",
              "| row | category | n | R@1 | R@3 | R@5 | R@10 | MRR | R@5 Wilson 95% |",
              "|---|---|---|---|---|---|---|---|---|"]
    for row, cats in res["retrieval"].items():
        for cat, v in cats.items():
            lines.append(f"| {row} | {cat} | {v['n']} | " + " | ".join(
                _fmt(v[f"recall@{k}"], 2) for k in KS) + f" | {_fmt(v['mrr'], 2)} | "
                + _ci(v["recall@5_wilson95"]) + " |")
    lines += ["", "Embedding latency (seconds): " + json.dumps(res["embedding_latency"]), "",
              "## Dedupe cosine distributions", ""]
    for variant, d in res["dedupe"].items():
        lines += [f"### {variant}", "", "| class | n | min | median | max |",
                  "|---|---|---|---|---|"]
        for lb, s in d["class_stats"].items():
            lines.append(f"| {lb} | {s['n']} | {_fmt(s['min'])} | {_fmt(s['median'])} "
                         f"| {_fmt(s['max'])} |")
        for k in ("dup@0.92", "related_band[0.75,0.92)", "linked@0.75 (dup or related)"):
            lines.append(f"\n{k}: precision={_fmt(d[k]['precision'], 2)} "
                         f"recall={_fmt(d[k]['recall'], 2)}")
        lines += ["", "| threshold | dup precision | dup recall | F1 |", "|---|---|---|---|"]
        lines += [f"| {s['threshold']:.2f} | {_fmt(s['dup_precision'], 2)} "
                  f"| {_fmt(s['dup_recall'], 2)} | {_fmt(s['dup_f1'], 2)} |"
                  for s in d["sweep"] if round(s["threshold"] * 100) % 5 == 0
                  or round(s["threshold"] * 100) in (92, 93)]
        lines.append("")
    lines += ["## Extraction", "", "```json", json.dumps(res["extraction"]["summary"], indent=1),
              "```", ""]
    return "\n".join(lines)


def main():  # pylint: disable=too-many-locals  # linear script entry
    """Run every phase in a temp home and write the results files."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n", maxsplit=1)[0])
    ap.add_argument("--chat", default="qwen2.5:0.5b")
    ap.add_argument("--embed", default="nomic-embed-text")
    ap.add_argument("--runs", type=int, default=5, help="extraction runs per document (>=5)")
    ap.add_argument("--extraction-docs", type=int, default=0, help="limit docs (smoke test only)")
    ap.add_argument("--out-dir", default=str(ROOT / "results"))
    args = ap.parse_args()
    real_home = Path.home() / "InfoParser"
    existed = real_home.exists()
    retrieval = json.loads((DATA / "retrieval.json").read_text(encoding="utf-8"))
    pairs = json.loads((DATA / "dedupe.json").read_text(encoding="utf-8"))
    extraction = json.loads((DATA / "extraction.json").read_text(encoding="utf-8"))
    if args.extraction_docs:
        extraction = extraction[:args.extraction_docs]
    env = environment(args.chat, args.embed)
    with tempfile.TemporaryDirectory(prefix="infoparser-eval-") as tmp:
        t0 = time.time()
        rets, latency, rankings = retrieval_phase(tmp, retrieval, args.chat, args.embed)
        print(f"retrieval done in {time.time() - t0:.0f}s", flush=True)
        dedupe = dedupe_phase(pairs, args.chat, args.embed)
        print("dedupe done", flush=True)
        extr = extraction_phase(extraction, args.chat, args.embed, args.runs)
        print(f"extraction done in {time.time() - t0:.0f}s total", flush=True)
    assert real_home.exists() == existed, "the eval touched ~/InfoParser"
    now = datetime.datetime.now(datetime.timezone.utc)
    res = {"date": now.strftime("%Y-%m-%d"), "finished_utc": now.isoformat(timespec="seconds"),
           "chat_model": args.chat, "embed_model": args.embed, "environment": env,
           "dataset": {"docs": len(retrieval["docs"]), "queries": len(retrieval["queries"]),
                       "dedupe_pairs": len(pairs), "extraction_docs": len(extraction)},
           "retrieval": rets, "embedding_latency": latency, "dedupe": dedupe,
           "extraction": extr, "query_rankings": rankings}
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = f"{res['date']}-{args.chat.replace(':', '-')}"
    (out / f"{stem}.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    (out / f"{stem}.md").write_text(markdown(res), encoding="utf-8")
    print(f"wrote {out / stem}.json and .md")


if __name__ == "__main__":
    main()
