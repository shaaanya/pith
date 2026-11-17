"""Standalone workers get unique ids and hold a lock that makes `restore --force` refuse."""

import fcntl
import re

import pytest

from pith import backup, cli, locks
from pith.config import load_config
from pith.services import build

QUOKKA = "Quokkas are small marsupials from Australia."


def _home(tmp_path):
    return tmp_path / "home"


def _populated(tmp_path):
    """A home with one queued item and a backup archive of it."""
    cfg = load_config(env={"PITH_HOME": str(_home(tmp_path))})
    svc = build(cfg)
    svc.inbox.submit(adapter="t", text=QUOKKA)
    archive = tmp_path / "a.tar.gz"
    backup.backup(cfg, archive)
    return svc, archive


def _restore(tmp_path, archive):
    cli.main(["--home", str(_home(tmp_path)), "restore", str(archive), "--force"])


def test_worker_ids_are_unique_per_call_and_name_the_process():
    """host-pid-random: two workers in one process still differ."""
    ids = {locks.new_worker_id() for _ in range(50)}
    assert len(ids) == 50
    assert all(re.search(r"-\d+-[0-9a-f]{6}$", i) for i in ids)


def test_cli_worker_uses_a_unique_id_not_w1(tmp_path, monkeypatch):
    """`pith worker` passes a fresh id to Worker."""
    seen = []

    class Fake:  # pylint: disable=too-few-public-methods  # stands in for Worker
        """Records the worker id and has no work."""

        def __init__(self, *_args, worker_id="w1"):
            seen.append(worker_id)

        def run_once(self):
            """No job."""
            return False

        def run_forever(self):
            """Never used by --once."""

    monkeypatch.setattr("pith.worker.Worker", Fake)
    for _ in range(2):
        cli.main(["--home", str(_home(tmp_path)), "worker", "--once"])
    assert len(set(seen)) == 2 and "w1" not in seen


def test_restore_refuses_while_a_standalone_process_holds_the_lock(tmp_path, capsys):
    """A worker/dashboard/watch/serve-http holds in-use.lock; restore --force must not proceed."""
    svc, archive = _populated(tmp_path)
    svc.conn.close()
    before = (_home(tmp_path) / "infoparser.db").read_bytes()
    with locks.in_use(_home(tmp_path)):
        with pytest.raises(SystemExit) as ex:
            _restore(tmp_path, archive)
        assert "is using" in str(ex.value)
    assert (_home(tmp_path) / "infoparser.db").read_bytes() == before
    _restore(tmp_path, archive)  # lock released: restore works
    assert "restored" in capsys.readouterr().out


def test_restore_refuses_while_a_job_lease_is_live(tmp_path):
    """A running job with an unexpired lease means a worker is mid-flight."""
    svc, archive = _populated(tmp_path)
    assert svc.queue.claim("some-worker") is not None
    svc.conn.close()
    with pytest.raises(SystemExit) as ex:
        _restore(tmp_path, archive)
    assert "live lease" in str(ex.value)


def test_expired_lease_does_not_block_restore(tmp_path, capsys):
    """After the lease runs out the worker is presumed dead and restore may proceed."""
    svc, archive = _populated(tmp_path)
    svc.queue.claim("some-worker")
    svc.conn.execute("UPDATE jobs SET lease_expires_at='2000-01-01T00:00:00Z'")
    svc.conn.close()
    _restore(tmp_path, archive)
    assert "restored" in capsys.readouterr().out


def test_long_running_commands_refuse_to_start_during_a_restore(tmp_path):
    """While restore holds the exclusive lock, a new worker/dashboard exits with a clear error."""
    _populated(tmp_path)[0].conn.close()
    with open(_home(tmp_path) / locks.LOCK_NAME, "a+", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        for cmd in (["worker", "--once"], ["watch", "--once"]):
            with pytest.raises(SystemExit) as ex:
                cli.main(["--home", str(_home(tmp_path)), *cmd])
            assert "restore is running" in str(ex.value)


def test_library_restore_refuses_while_in_use_lock_is_held(tmp_path):
    """backup.restore itself enforces the guard: no caller can bypass it."""
    svc, archive = _populated(tmp_path)
    svc.conn.close()
    before = (_home(tmp_path) / "infoparser.db").read_bytes()
    with locks.in_use(_home(tmp_path)):
        with pytest.raises(locks.InUseError, match="is using"):
            backup.restore(archive, _home(tmp_path), force=True)
    assert (_home(tmp_path) / "infoparser.db").read_bytes() == before


def test_library_restore_refuses_while_a_lease_is_live(tmp_path):
    """The live-lease check also lives in the library call."""
    svc, archive = _populated(tmp_path)
    assert svc.queue.claim("some-worker") is not None
    svc.conn.close()
    with pytest.raises(locks.InUseError, match="live lease"):
        backup.restore(archive, _home(tmp_path), force=True)


def test_library_restore_refuses_while_run_lock_is_held(tmp_path):
    """A running `pith run` holds run.lock; the library call still refuses."""
    svc, archive = _populated(tmp_path)
    svc.conn.close()
    with open(_home(tmp_path) / "run.lock", "a+", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(backup.RestoreError, match="running"):
            backup.restore(archive, _home(tmp_path), force=True)


def test_library_restore_works_when_nothing_holds_a_lock(tmp_path):
    """Guard acquired inside restore is released afterwards (second restore succeeds)."""
    svc, archive = _populated(tmp_path)
    svc.conn.close()
    backup.restore(archive, _home(tmp_path), force=True)
    backup.restore(archive, _home(tmp_path), force=True)
