"""Shared fixtures: a throwaway service, a queue drain and an embedder router."""
import pytest
from stubs.hash_embedder import HashEmbedder

from pith.config import load_config
from pith.pipeline import runner
from pith.services import build
from pith.worker import Worker


@pytest.fixture(name="svc")
def svc_fixture(tmp_path):
    """Services over a fresh home under tmp_path."""
    return build(load_config(env={"PITH_HOME": str(tmp_path / "home")}))


@pytest.fixture
def drain():
    """Callable that runs the worker over a service until its queue is empty."""
    def go(service):
        w = Worker(service.conn, service.inbox, service.queue,
                   lambda i: runner.process(service, i))
        while w.run_once():
            pass
    return go


@pytest.fixture
def use_embedder(monkeypatch):
    """Callable routing registry.first('embed') to a HashEmbedder (or None to remove it)."""
    originals = {}

    def go(service, embedder="default"):
        emb = HashEmbedder() if embedder == "default" else embedder
        registry = service.registry
        # first call per registry wins (the real `first`); keeping the registry alive pins its id
        _, orig = originals.setdefault(id(registry), (registry, registry.first))
        monkeypatch.setattr(registry, "first", lambda task: emb if task == "embed" else orig(task))
        return emb
    return go
