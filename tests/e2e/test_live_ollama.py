"""Live Ollama checks. Skip cleanly unless a server answers AND the env-named models exist.

Model names come ONLY from env: INFOPARSER_LIVE_CHAT_MODEL, INFOPARSER_LIVE_EMBED_MODEL.
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


def _report(res, label, record_property):
    stated, downgraded, _ = check_contract(res)
    by = sorted({r[0] for r in db(res["svc"]).execute("SELECT extracted_by FROM knowledge_items")})
    info = (f"{label}: stated={stated} downgraded={downgraded} extracted_by={by} "
            f"search={res['search'].mode} ask={res['answer'].mode}")
    print(info)
    record_property("live_result", info)
    return by


def test_live_ollama_pipeline(tmp_path, record_property):
    """Full pipeline against real local Ollama chat + embedding models (openai_compat)."""
    chat, emb = _need("INFOPARSER_LIVE_CHAT_MODEL"), _need("INFOPARSER_LIVE_EMBED_MODEL")
    res = run_workflow_cfg(cfg_live(tmp_path / "live", chat, emb))
    by = _report(res, "openai_compat", record_property)
    assert res["search"].mode == "hybrid"
    assert by  # extracted_by recorded (ollama:<model> or heuristic fallback; both are reported)


def test_live_ollama_cli(tmp_path, record_property):
    """Same pipeline through the cli backend running `ollama run <model>`."""
    if not shutil.which("ollama"):
        pytest.skip("`ollama` binary not on PATH")
    chat = _need("INFOPARSER_LIVE_CHAT_MODEL")
    res = run_workflow_cfg(cfg_live_cli(tmp_path / "livecli", chat))
    _report(res, "cli(ollama run)", record_property)
