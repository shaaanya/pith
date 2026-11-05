"""Worker default ids are unique per instance; explicit ids are honoured."""

import pytest

from infoparser.config import load_config
from infoparser.inbox.service import Inbox
from infoparser.jobs import JobQueue
from infoparser.store.blobs import BlobStore
from infoparser.store.db import connect, migrate
from infoparser.worker import Processed, Worker


@pytest.fixture(name="env")
def _env(tmp_path):
    cfg = load_config(env={"INFOPARSER_HOME": str(tmp_path)})
    conn = connect(cfg.db_path)
    migrate(conn)
    return Inbox(conn, BlobStore(cfg.blobs_dir), cfg), JobQueue(conn, cfg)


def _worker(env, **kw):
    inbox, queue = env
    return Worker(inbox.conn, inbox, queue, lambda _iid: Processed(), **kw)


def test_default_worker_ids_are_unique(env):
    """Two default Workers (even in one process) never share an id, and none is "w1"."""
    a, b = _worker(env), _worker(env)
    assert a.worker_id != b.worker_id
    assert "w1" not in (a.worker_id, b.worker_id)


def test_default_id_workers_own_their_own_claim(env):
    """Each default-id worker claims one distinct job; the lease owner is that worker's id."""
    inbox = env[0]
    for text in ("one", "two"):
        inbox.submit(adapter="t", text=text)
    a, b = _worker(env), _worker(env)
    assert a.run_once() and b.run_once()
    owners = {r[0] for r in inbox.conn.execute("SELECT worker_id FROM jobs")}
    assert len(owners) == 2 and owners == {a.worker_id, b.worker_id}


def test_explicit_worker_id_is_honoured(env):
    """An explicit id is kept as given."""
    assert _worker(env, worker_id="mine").worker_id == "mine"
