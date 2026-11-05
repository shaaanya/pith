"""Model-independence harness: one scenario, many interchangeable backend configs."""
import json
import os
import re
import sqlite3
import sys
from pathlib import Path
from typing import cast

import pytest
from stubs.http_fixture_server import FIXTURES, FixtureServer, Route
from stubs import openai_stub, stated_llm
from stubs.openai_stub import OpenAIStub

from infoparser.config import load_config
from infoparser.export import export_vault
from infoparser.pipeline import runner
from infoparser.retrieval.ask import ask
from infoparser.retrieval.search import search_ex
from infoparser.services import build
from infoparser.worker import Worker

STATED_LLM = str(Path(__file__).parent.parent / "stubs" / "stated_llm.py")
LIVE_TIMEOUT = 120
FRONTMATTER_KEYS = {"id", "kind", "title", "provenance", "source_url", "source_title", "created",
                    "updated", "topics", "entities", "locators"}


def ollama_base() -> str:
    """Ollama server URL, honouring OLLAMA_HOST (default 127.0.0.1:11434)."""
    raw = os.environ.get("OLLAMA_HOST") or "127.0.0.1:11434"
    if "://" not in raw:
        raw = "http://" + raw
    if not re.search(r":\d+$", raw):
        raw += ":11434"
    return raw.replace("//0.0.0.0", "//127.0.0.1")

NOTE = ("Hybrid retrieval fuses keyword search and embeddings. "
        "Rank fusion needs no score calibration.")
COLLECTION = "Top reading list: Vector Search Basics, Hybrid retrieval notes, Chunking guide"


def db(svc) -> sqlite3.Connection:
    """Services.conn is annotated `object`; narrow it for type-aware linting.

    vars() keeps pylint from inferring the `object` annotation through typing.cast.
    """
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
        cfg.backends = {"c": {"type": "cli", "command": [sys.executable, STATED_LLM]}}
        cfg.tasks = {"distill": ["c"], "answer": ["c"]}
    return cfg


def cfg_live(home, chat, embed):
    """Config pointing at a local Ollama; model names are supplied by the caller (env)."""
    cfg = load_config(env={"INFOPARSER_HOME": str(home)})
    cfg.backends = {"ollama": {"type": "openai_compat", "base_url": ollama_base() + "/v1",
                               "model": chat, "embed_model": embed, "timeout": LIVE_TIMEOUT}}
    cfg.tasks = {"distill": ["ollama"], "answer": ["ollama"], "embed": ["ollama"]}
    return cfg


def cfg_live_cli(home, chat):
    """Config running `ollama run <chat>` through the cli backend (prompt on stdin)."""
    cfg = load_config(env={"INFOPARSER_HOME": str(home)})
    cfg.backends = {"ollama_cli": {"type": "cli", "command": ["ollama", "run", chat],
                                   "timeout": LIVE_TIMEOUT}}
    cfg.tasks = {"distill": ["ollama_cli"], "answer": ["ollama_cli"]}
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


def _norm(text):
    return re.sub(r"\s+", " ", text or "").strip().casefold()


def stated_report(svc):
    """Assert every stored `stated` item quotes its referenced segment verbatim (modulo case and
    whitespace; independent of production code). Returns (stated_count, downgraded_count)."""
    conn = db(svc)
    rows = conn.execute("SELECT * FROM knowledge_items WHERE deleted_at IS NULL").fetchall()
    stated, downgraded = 0, 0
    for it in rows:
        data = json.loads(it["data_json"])
        if it["provenance"] == "stated":
            stated += 1
            texts = [_norm(conn.execute("SELECT text FROM segments WHERE id=?", (s,)).fetchone()[0])
                     for s in json.loads(it["segment_refs"])]
            quote = _norm(data.get("evidence"))
            assert quote and texts and any(quote in t for t in texts), (it["title"], quote)
        elif data.get("flag") == "evidence_not_found":
            downgraded += 1
            assert it["provenance"] == "inferred"
    return stated, downgraded


def _frontmatter_keys(path):
    lines = path.read_text(encoding="utf-8").split("---\n")[1].splitlines()
    return {ln.split(":", 1)[0] for ln in lines}


def check_contract(res):
    """Structural contract shared by every backend. Returns (stated, downgraded, shape)."""
    svc, conn = res["svc"], db(res["svc"])
    assert [svc.inbox.get(i)["status"] for i in res["ids"]] == ["processed"] * 3
    items = conn.execute("SELECT * FROM knowledge_items WHERE deleted_at IS NULL").fetchall()
    assert items, "no items produced"
    for it in items:
        assert it["provenance"] in ("stated", "inferred", "external")
        assert it["extracted_by"] and it["source_id"] and it["title"]
        assert it["body"].strip()  # empty model output is rejected by distill, never stored
        assert isinstance(json.loads(it["data_json"]), dict)
        assert isinstance(json.loads(it["segment_refs"]), list)
    assert "summary" in {it["kind"] for it in items}
    stated, downgraded = stated_report(svc)
    assert res["search"].hits and res["search"].mode in ("hybrid", "fts")
    ans = res["answer"]
    assert ans.mode in ("answer", "retrieval-only") and ans.retrieved
    assert set(ans.citations) <= {e.n for e in ans.retrieved} and not ans.invalid_citations
    if ans.mode == "answer":
        assert ans.citations and ans.generated_by
    else:
        assert ans.message  # degraded mode is labelled, never silent
    files = list(Path(svc.cfg.vault_dir).glob("*/*.md"))
    assert res["exported"] == len(items) == len(files)
    keys = {frozenset(_frontmatter_keys(f)) for f in files}
    assert keys == {frozenset(FRONTMATTER_KEYS)}  # export shape is the same for every item
    return stated, downgraded, frozenset(FRONTMATTER_KEYS)


@pytest.fixture(name="stub")
def stub_fixture(monkeypatch):
    """In-process OpenAI-style stub server whose distill replies include stated + fabricated."""
    monkeypatch.setattr(openai_stub, "reply_for", stated_llm.reply_for)
    with OpenAIStub() as server:
        yield server
