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
