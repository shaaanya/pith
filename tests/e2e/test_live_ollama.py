"""Live Ollama check. Skips cleanly unless a server answers AND the env-named models exist.

Model names come ONLY from env: INFOPARSER_LIVE_CHAT_MODEL, INFOPARSER_LIVE_EMBED_MODEL.
"""
import json
import os
import urllib.error
import urllib.request

import pytest

from .conftest import cfg_live, check_contract, db, run_workflow_cfg

pytestmark = pytest.mark.live_ollama
HOST = "http://127.0.0.1:11434"


def _installed():
    try:
        with urllib.request.urlopen(HOST + "/api/tags", timeout=2) as resp:
            return {m["name"] for m in json.load(resp).get("models", [])}
    except (OSError, ValueError, urllib.error.URLError) as err:
        return pytest.skip(f"Ollama not reachable at {HOST}: {type(err).__name__}")


def _need(env):
    name = os.environ.get(env)
    if not name:
        pytest.skip(f"{env} not set")
    have = _installed()
    if not {name, name + ":latest"} & have:
        pytest.skip(f"model from {env} not installed (installed: {sorted(have) or 'none'})")
    return name


def test_live_ollama_pipeline(tmp_path):
    """Full pipeline against a real local Ollama chat + embedding model."""
    chat, emb = _need("INFOPARSER_LIVE_CHAT_MODEL"), _need("INFOPARSER_LIVE_EMBED_MODEL")
    res = run_workflow_cfg(cfg_live(tmp_path / "live", chat, emb))
    check_contract(res)
    by = db(res["svc"]).execute("SELECT extracted_by FROM knowledge_items")
    assert any(x["extracted_by"].startswith("ollama:") for x in by)
    assert res["search"].mode == "hybrid"
