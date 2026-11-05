"""Fixtures for provider tests: loopback stubs, a Config factory, one backend per kind."""
import sys
from pathlib import Path

import pytest
from stubs.anthropic_stub import AnthropicStub
from stubs.openai_stub import OpenAIStub

from infoparser.config import Config
from infoparser.providers.anthropic import AnthropicBackend
from infoparser.providers.cli_backend import CliBackend
from infoparser.providers.heuristic import HeuristicBackend
from infoparser.providers.openai_compat import OpenAICompatBackend
from infoparser.providers.ports import Capabilities

FAKE_LLM = str(Path(__file__).parent.parent / "stubs" / "fake_llm.py")


@pytest.fixture(name="stub")
def stub_fixture():
    """Running OpenAI-wire stub."""
    with OpenAIStub() as s:
        yield s


@pytest.fixture
def make_cfg(tmp_path):
    """Factory for a Config rooted in tmp_path."""
    def _make(specs, tasks=None, allow_remote=False):
        return Config(home=tmp_path, db_path=tmp_path / "db", blobs_dir=tmp_path / "b",
                      vault_dir=tmp_path / "v", backends=specs, tasks=tasks or {},
                      allow_remote=allow_remote)
    return _make


@pytest.fixture(name="anthropic_stub")
def anthropic_stub_fixture():
    """Running Anthropic-wire stub."""
    with AnthropicStub() as s:
        yield s


@pytest.fixture
def backends(stub, anthropic_stub, monkeypatch):
    """One backend of each kind, wired to the stubs."""
    monkeypatch.setenv("IP_CONTRACT_KEY", "k")
    return {
        "heuristic": HeuristicBackend(),
        "openai_compat": OpenAICompatBackend("oa", stub.base_url, "m", embed_model="e",
                                             capabilities=Capabilities(json_mode=True)),
        "cli": CliBackend("cli", [sys.executable, FAKE_LLM]),
        "anthropic": AnthropicBackend("an", "m", "IP_CONTRACT_KEY",
                                      base_url=anthropic_stub.base_url),
    }
