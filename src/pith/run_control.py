"""Per-home run ownership and cooperative shutdown, without signalling saved PIDs.

The persistent flock is the liveness/completion authority. Every run publishes a fresh
instance id; stop requests name that instance, so stale requests cannot stop a later run.
"""
from __future__ import annotations

import fcntl
import json
import math
import os
import stat
import tempfile
import time
import uuid
from pathlib import Path

from pith import locks

POLL_SECONDS = 0.1


class RunError(Exception):
    """A run cannot start, failed, or could not be stopped cleanly."""


def _open_lock(path: Path, *, create: bool = False):
    """Open the persistent regular inode, never a symlink or blocking special file."""
    flags = (os.O_RDWR if create else os.O_RDONLY) | os.O_NONBLOCK | os.O_NOFOLLOW
    if create:
        flags |= os.O_CREAT
    fd = os.open(path, flags, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise RunError(f"not a regular run lock: {path}")
        return os.fdopen(fd, "r+" if create else "r", encoding="utf-8")
    except BaseException:
        os.close(fd)
        raise


def _record(f) -> dict:
    f.seek(0)
    try:
        text = f.read()
    except UnicodeDecodeError:
        return {"unsupported": True}
    try:
        record = json.loads(text)
    except ValueError:
        return {"unsupported": True} if text.strip() else {}
    return record if isinstance(record, dict) else {"unsupported": True}


def _instance(record: dict) -> str | None:
    value = record.get("instance")
    if isinstance(value, str) and len(value) == 32 and all(c in "0123456789abcdef" for c in value):
        return value
    return None


def _free(f) -> bool:
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    return True


def _request_path(home: Path, instance: str) -> Path:
    return home / f"run.stop-{instance}"


class RunLock:  # pylint: disable=too-few-public-methods
    """Held until all threads and connections have finished, including slow shutdown."""

    def __init__(self, home: Path):
        locks.ensure_private_home(home)
        self.home = home
        self.instance = uuid.uuid4().hex
        self.request = _request_path(home, self.instance)
        self.f = _open_lock(home / "run.lock", create=True)
        try:
            if not _free(self.f):
                pid = _record(self.f).get("pid", "?")
                raise RunError(f"already running for {home} (pid {pid}); use `pith stop` first")
            self.f.seek(0)
            self.f.truncate()
            json.dump({"version": 1, "pid": os.getpid(), "instance": self.instance}, self.f)
            self.f.flush()
        except BaseException:
            self.f.close()
            raise

    def stop_requested(self) -> bool:
        """Only this instance's request counts; no directory scan or PID lookup."""
        return self.request.is_file()

    def release(self) -> None:
        """Never unlink run.lock: waiters and replacement runs share its inode."""
        try:
            self.request.unlink(missing_ok=True)
            self.f.seek(0)
            self.f.truncate()
        finally:
            self.f.close()


def _write_request(home: Path, instance: str) -> None:
    """Publish a complete private request; late writers cannot affect another instance."""
    fd, temporary = tempfile.mkstemp(prefix=".run-stop-", dir=home)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(instance + "\n")
        os.replace(temporary, _request_path(home, instance))
    finally:
        Path(temporary).unlink(missing_ok=True)


def stop(home: Path, timeout: float = 30) -> bool:
    """Request shutdown and wait for completion. False means already not running.

    A timeout leaves the request in place, never kills a worker, and never claims success.
    An instance change proves the original completed; the replacement is left alone.
    """
    if not math.isfinite(timeout) or timeout <= 0:
        raise RunError("--timeout must be a finite number greater than zero")
    home = Path(home)
    try:
        f = _open_lock(home / "run.lock")
    except FileNotFoundError:
        return False
    except OSError as e:
        raise RunError(f"cannot open run lock for {home}: {e}") from e
    deadline = time.monotonic() + timeout
    try:
        with f:
            if _free(f):
                return False
            # A starting process holds its flock before publishing the metadata.
            record = _record(f)
            while not (instance := _instance(record)):
                if _free(f):
                    return False
                if record or time.monotonic() >= deadline:
                    raise RunError(f"running instance for {home} has no shutdown metadata; "
                                   "stop it with Ctrl-C, then restart with this version of Pith")
                time.sleep(min(POLL_SECONDS, max(0, deadline - time.monotonic())))
                record = _record(f)
            _write_request(home, instance)
            while True:
                if _free(f) or (current := _instance(_record(f))) not in (None, instance):
                    return True
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RunError(f"shutdown requested for {home}, but it is still stopping after "
                                   f"{timeout:g}s; active work is allowed to finish. "
                                   "Run `pith stop --timeout 120` to wait longer")
                time.sleep(min(POLL_SECONDS, remaining))
    except OSError as e:
        raise RunError(f"cannot stop Pith for {home}: {e}") from e
