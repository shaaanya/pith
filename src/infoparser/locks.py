"""Process guards: unique worker ids and the in-use lock that makes `restore` see other processes.

Every long-running command that touches the database (worker, watch, dashboard, serve-http) holds
a SHARED flock on <home>/in-use.lock. `restore` takes it EXCLUSIVELY (so it refuses while any of
them runs) and also refuses while a job lease is live. `infoparser run` is covered by its own
run.lock. The OS releases flocks when a process dies, so a crash never leaves a stale lock.
"""

import fcntl
import os
import socket
import sqlite3
import secrets
from contextlib import contextmanager
from pathlib import Path

from infoparser.ids import utcnow

LOCK_NAME = "in-use.lock"


class InUseError(Exception):
    """The home is being restored, or (for restore) is in use by another process."""


def new_worker_id() -> str:
    """A worker id that is unique per process: host, pid and a random suffix."""
    return f"{socket.gethostname()}-{os.getpid()}-{secrets.token_hex(3)}"


@contextmanager
def _flock(home: Path, mode: int, busy: str):
    home = Path(home)
    home.mkdir(parents=True, exist_ok=True)
    with open(home / LOCK_NAME, "a+", encoding="utf-8") as f:
        try:
            fcntl.flock(f, mode | fcntl.LOCK_NB)
        except BlockingIOError:
            raise InUseError(busy) from None
        yield


def in_use(home: Path):
    """Hold the shared lock while this process works on the database in `home`."""
    busy = f"a restore is running for {home}; try again when it is done"
    return _flock(home, fcntl.LOCK_SH, busy)


def live_leases(db: Path) -> int:
    """Running jobs whose lease has not expired yet (0 when there is no database)."""
    if not Path(db).exists():
        return 0
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=3)
    try:
        return conn.execute(
            "SELECT count(*) FROM jobs WHERE state='running' AND lease_expires_at>?", (utcnow(),)
        ).fetchone()[0]
    except sqlite3.DatabaseError:
        return 0  # no jobs table or an unreadable file: restore's own checks deal with it
    finally:
        conn.close()


@contextmanager
def restore_guard(home: Path, db: Path):
    """Refuse a restore while any standalone process uses `home` or a job lease is live."""
    if not Path(db).exists():  # nothing can be using a home that has no database yet
        yield
        return
    busy = (f"a worker, watcher, dashboard or ingest server is using {home}; "
            "stop it before restoring")
    with _flock(home, fcntl.LOCK_EX, busy):
        if n := live_leases(db):
            raise InUseError(f"{n} job(s) hold a live lease (a worker is processing); "
                             "stop all workers and wait for the leases to expire before restoring")
        yield
