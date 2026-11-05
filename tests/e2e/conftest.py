"""Model-independence harness: one scenario, many interchangeable backend configs."""
import json
import sqlite3
import sys
from pathlib import Path
from typing import cast

import pytest
from stubs.http_fixture_server import FIXTURES, FixtureServer, Route
from stubs.openai_stub import OpenAIStub

from infoparser.config import load_config
from infoparser.export import export_vault
from infoparser.pipeline import runner
from infoparser.pipeline.provenance import evidence_in
from infoparser.retrieval.ask import ask
from infoparser.retrieval.search import search_ex
from infoparser.services import build
from infoparser.worker import Worker

FAKE_LLM = str(Path(__file__).parent.parent / "stubs" / "fake_llm.py")
OLLAMA_V1 = "http://127.0.0.1:11434/v1"

NOTE = ("Hybrid retrieval fuses keyword search and embeddings. "
        "Rank fusion needs no score calibration.")
COLLECTION = "Top reading list: Vector Search Basics, Hybrid retrieval notes, Chunking guide"


def db(svc) -> sqlite3.Connection:
    """Services.conn is annotated `object`; narrow it for type-aware linting."""
    return cast(sqlite3.Connection, vars(svc)["conn"])


def cfg_for(variant, home, stub_url=None):
    """Config for one backend variant: heuristic | openai_compat | cli."""
    cfg = load_config(env={"INFOPARSER_HOME": str(home)})
    if variant == "heuristic":
        cfg.backends, cfg.tasks = {"h": {"type": "heuristic"}}, {}
    elif variant == "openai_compat":
        cfg.backends = {"m": {"type": "openai_compat", "base_url": stub_url,
                              "model": "stub-model", "embed_model": "stub-embed"}}
        cfg.tasks = {"distill": ["m"], "answer": ["m"], "embed": ["m"]}
    elif variant == "cli":
        cfg.backends = {"c": {"type": "cli", "command": [sys.executable, FAKE_LLM]}}
        cfg.tasks = {"distill": ["c"], "answer": ["c"]}
    return cfg


def cfg_live(home, chat, embed):
    """Config pointing at a local Ollama; model names are supplied by the caller (env)."""
    cfg = load_config(env={"INFOPARSER_HOME": str(home)})
    cfg.backends = {"ollama": {"type": "openai_compat", "base_url": OLLAMA_V1,
                               "model": chat, "embed_model": embed, "timeout": 300}}
    cfg.tasks = {"distill": ["ollama"], "answer": ["ollama"], "embed": ["ollama"]}
    return cfg


def drain(svc):
    """Run the worker until the queue is empty."""
    worker = Worker(db(svc), svc.inbox, svc.queue, lambda i: runner.process(svc, i))
    while worker.run_once():
        pass


def submit_notes(svc):
    """Submit the two text-only scenario items and process them."""
    ids = [svc.inbox.submit(adapter="t", text=t).id for t in (NOTE, COLLECTION)]
    drain(svc)
    return ids


def submit_scenario(svc, base):
    """Submit article URL + note + collection note and process them."""
    ids = [svc.inbox.submit(adapter="t", text=f"{base}/article").id]
    ids += [svc.inbox.submit(adapter="t", text=t).id for t in (NOTE, COLLECTION)]
    drain(svc)
    return ids


def run_workflow_cfg(cfg):
    """submit -> process -> distill -> search -> ask -> export. Returns a result dict."""
    svc = build(cfg)
    with FixtureServer({"/article": Route(FIXTURES / "article.html")}) as srv:
        ids = submit_scenario(svc, srv.base)
    res = search_ex(svc, "vector search chunking")
    ans = ask(svc, "What does vector search do?")
    return {"svc": svc, "ids": ids, "search": res, "answer": ans, "exported": export_vault(svc)}


def run_workflow(variant, home, stub_url=None):
    """run_workflow_cfg for a named variant."""
    return run_workflow_cfg(cfg_for(variant, home, stub_url))


def check_contract(res):
    """Structural contract shared by every backend; returns the item row shape."""
    svc, conn = res["svc"], db(res["svc"])
    assert [svc.inbox.get(i)["status"] for i in res["ids"]] == ["processed"] * 3
    items = conn.execute("SELECT * FROM knowledge_items WHERE deleted_at IS NULL").fetchall()
    assert items, "no items produced"
    for it in items:
        assert it["provenance"] in ("stated", "inferred", "external")
        assert it["extracted_by"]
        if it["provenance"] == "stated":  # evidence must be a real quote of a referenced segment
            ev = json.loads(it["data_json"]).get("evidence")
            segs = [conn.execute("SELECT text FROM segments WHERE id=?", (s,)).fetchone()["text"]
                    for s in json.loads(it["segment_refs"])]
            assert segs and any(evidence_in(ev, t) for t in segs), (it["title"], ev)
    assert res["search"].hits and res["search"].mode in ("hybrid", "fts")
    ans = res["answer"]
    assert ans.mode in ("answer", "retrieval-only") and ans.retrieved
    assert set(ans.citations) <= {e.n for e in ans.retrieved} and not ans.invalid_citations
    if ans.mode == "answer":
        assert ans.citations and ans.generated_by
    else:
        assert ans.message  # degraded mode is labelled, never silent
    assert res["exported"] >= 1
    return {tuple(sorted(dict(it).keys())) for it in items}


@pytest.fixture(name="stub")
def stub_fixture():
    """In-process OpenAI-style stub server."""
    with OpenAIStub() as server:
        yield server
