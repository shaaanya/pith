import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))  # makes `stubs` importable

import pytest

from infoparser.config import load_config
from infoparser.services import build
from infoparser.worker import Worker
from infoparser.pipeline import runner


@pytest.fixture
def svc(tmp_path):
    return build(load_config(env={"INFOPARSER_HOME": str(tmp_path / "home")}))


@pytest.fixture
def drain():
    def go(svc):
        w = Worker(svc.conn, svc.inbox, svc.queue, lambda i: runner.process(svc, i))
        while w.run_once():
            pass
    return go


from stubs.hash_embedder import HashEmbedder  # noqa: E402


@pytest.fixture
def use_embedder():
    def go(svc, embedder="default"):
        """Route registry.first('embed') to a HashEmbedder (or None to remove the embedder)."""
        emb = HashEmbedder() if embedder == "default" else embedder
        if not hasattr(svc.registry, "_orig_first"):
            svc.registry._orig_first = svc.registry.first
        orig = svc.registry._orig_first
        svc.registry.first = lambda task: emb if task == "embed" else orig(task)
        return emb
    return go
