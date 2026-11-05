import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))  # makes `stubs` importable

from stubs.openai_stub import OpenAIStub  # noqa: E402

FAKE_LLM = str(Path(__file__).parent.parent / "stubs" / "fake_llm.py")


@pytest.fixture
def stub():
    with OpenAIStub() as s:
        yield s


@pytest.fixture
def make_cfg(tmp_path):
    from infoparser.config import Config

    def _make(backends, tasks=None, allow_remote=False):
        return Config(home=tmp_path, db_path=tmp_path / "db", blobs_dir=tmp_path / "b",
                      vault_dir=tmp_path / "v", backends=backends, tasks=tasks or {},
                      allow_remote=allow_remote)
    return _make


@pytest.fixture
def backends(stub):
    from infoparser.providers.cli_backend import CliBackend
    from infoparser.providers.heuristic import HeuristicBackend
    from infoparser.providers.openai_compat import OpenAICompatBackend
    from infoparser.providers.ports import Capabilities
    return {
        "heuristic": HeuristicBackend(),
        "openai_compat": OpenAICompatBackend("oa", stub.base_url, "m", embed_model="e",
                                             capabilities=Capabilities(json_mode=True)),
        "cli": CliBackend("cli", [sys.executable, FAKE_LLM]),
    }
