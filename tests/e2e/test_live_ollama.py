"""Live Ollama checks. Skip cleanly unless a server answers AND the env-named models exist.

Model names come ONLY from env: PITH_LIVE_CHAT_MODEL, PITH_LIVE_EMBED_MODEL.
The server URL honours OLLAMA_HOST (default 127.0.0.1:11434). Prerequisites: `ollama serve`
running and the models fetched with `ollama pull <model>` (neither is done by these tests).
"""
import json
import os
import shutil
import urllib.error
import urllib.request

import pytest

from .conftest import (cfg_live, cfg_live_cli, check_contract, db, ollama_base,
                       run_workflow_cfg)

pytestmark = pytest.mark.live_ollama


def _installed():
    try:
        with urllib.request.urlopen(ollama_base() + "/api/tags", timeout=2) as resp:
            return {m["name"] for m in json.load(resp).get("models", [])}
    except (OSError, ValueError, urllib.error.URLError) as err:
        return pytest.skip(f"Ollama not reachable at {ollama_base()}: {type(err).__name__}")


def _need(env):
    name = os.environ.get(env)
    if not name:
        pytest.skip(f"{env} not set")
    have = _installed()
    if not {name, name + ":latest"} & have:
        pytest.skip(f"model from {env} not installed (installed: {sorted(have) or 'none'})")
    return name


def _report(res, label, backend, record_property):
    """Check the contract, require every item to come from `backend` or the heuristic fallback,
    and record how many were model-made. Model acceptance itself is never asserted: a tiny
    model is nondeterministic (observed 0 to 9 of ~10 items accepted across runs)."""
    stated, downgraded, _ = check_contract(res)
    rows = db(res["svc"]).execute("SELECT extracted_by FROM knowledge_items").fetchall()
    by = [r[0] for r in rows]
    assert all(b.startswith((backend + ":", "heuristic:")) for b in by), set(by)
    made = sum(b.startswith(backend + ":") for b in by)
    info = (f"{label}: model_made={made}/{len(by)} stated={stated} downgraded={downgraded} "
            f"search={res['search'].mode} ask={res['answer'].mode}")
    print(info)
    record_property("live_result", info)


def test_live_ollama_pipeline(tmp_path, record_property):
    """Full pipeline against real local Ollama chat + embedding models (openai_compat)."""
    chat, emb = _need("PITH_LIVE_CHAT_MODEL"), _need("PITH_LIVE_EMBED_MODEL")
    res = run_workflow_cfg(cfg_live(tmp_path / "live", chat, emb))
    _report(res, "openai_compat", "ollama", record_property)
    # deterministic parts: the real embedding model produced vectors and search used them
    models = {r[0] for r in db(res["svc"]).execute("SELECT DISTINCT model_id FROM embeddings")}
    assert models == {f"ollama:{emb}"}
    assert res["search"].mode == "hybrid"


def test_live_ollama_cli(tmp_path, record_property):
    """Same pipeline through the cli backend running `ollama run <model>`."""
    if not shutil.which("ollama"):
        pytest.skip("`ollama` binary not on PATH")
    chat = _need("PITH_LIVE_CHAT_MODEL")
    res = run_workflow_cfg(cfg_live_cli(tmp_path / "livecli", chat))
    _report(res, "cli(ollama run)", "ollama_cli", record_property)
