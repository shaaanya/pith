"""`infoparser run`: dashboard + worker loop + fs watcher in one process, clean shutdown.

One `run` per home: <home>/run.lock is held with flock (released by the OS if we die, so no
stale-lock or PID-reuse races); the PID inside is only for the error message. Each thread owns
its SQLite connection. A thread that crashes prints its traceback to stderr and stops the whole
run (RunError), so the dashboard never keeps serving a dead worker. Not included: http ingest
(use `infoparser serve-http`)."""
from __future__ import annotations

import fcntl
import os
import sys
import threading
import traceback
from pathlib import Path

from infoparser import locks
from infoparser.adapters.fs import FsAdapter
from infoparser.dashboard.server import make_server
from infoparser.pipeline import runner
from infoparser.services import build
from infoparser.worker import Worker

JOIN_SECONDS = 30


class RunError(Exception):
    """`run` cannot start or a thread crashed."""


class _Lock:  # pylint: disable=too-few-public-methods  # acquire in __init__, release()
    """The per-home run.lock, held with flock until release()."""

    def __init__(self, home: Path):
        locks.ensure_private_home(home)
        self.path = home / "run.lock"
        # held for the lifetime of the run, closed in release(): a `with` block cannot express that
        self.f = open(self.path, "a+", encoding="utf-8")  # pylint: disable=consider-using-with
        try:
            fcntl.flock(self.f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.f.seek(0)
            pid = self.f.read().strip() or "?"
            self.f.close()
            raise RunError(f"already running for {home} (pid {pid}); stop it first") from None
        self.f.seek(0)
        self.f.truncate()
        self.f.write(str(os.getpid()))
        self.f.flush()

    def release(self) -> None:
        """Drop the lock. The file is never unlinked while a flock may be held (avoids
        lock-on-orphan-inode races)."""
        self.f.truncate(0)
        self.f.close()


class _Threads:
    """Named worker threads that stop the whole run if any of them dies."""

    def __init__(self, stop: threading.Event):
        self.stop = stop
        self.items: list[tuple[threading.Thread, list]] = []  # (thread, [its connections])
        self.crashed: list[str] = []

    def add(self, name, fn) -> threading.Thread:
        """A thread running `fn(conns)`; a crash prints the traceback and sets `stop`."""
        conns: list = []

        def target():
            try:
                fn(conns)
            # a dead thread must take the whole run down, loudly
            except BaseException:  # noqa: BLE001  # pylint: disable=broad-exception-caught
                traceback.print_exc()
                self.crashed.append(name)
                self.stop.set()
        t = threading.Thread(target=target, name=name)
        self.items.append((t, conns))
        return t

    def join_all(self) -> None:
        """Join every started thread, then close the connections of those that stopped."""
        for t, conns in self.items:
            if not t.is_alive() and not t.ident:
                continue
            t.join(JOIN_SECONDS)
            if t.is_alive():
                print(f"warning: thread {t.name} did not stop within {JOIN_SECONDS}s; "
                      "leaving its connection open", file=sys.stderr)
                continue
            for c in conns:
                c.close()


def _worker(cfg, stop, conns, live) -> None:
    """Thread body: process jobs with its own connection until `stop`. Its Services is added to
    `live` so a settings save can swap the registry."""
    s = build(cfg)
    live.append(s)
    conns.append(s.conn)
    Worker(s.conn, s.inbox, s.queue, lambda i: runner.process(s, i),
           worker_id="run").run_forever(0.5, stop)


def _watcher(cfg, stop, conns) -> None:
    """Thread body: poll the drop folders with its own connection until `stop`."""
    s = build(cfg)
    conns.append(s.conn)
    FsAdapter(s.inbox, s.cfg.watch_dirs).run_forever(5.0, stop)


def _make_dashboard(svc, port: int):
    """Bind the dashboard server; RunError if the port is unavailable."""
    try:
        return make_server(svc, port=port)
    except OSError as e:
        raise RunError(f"port {port} in use or unavailable: {e}") from e


def run(cfg, port: int = 8777, *,  # pylint: disable=too-many-arguments  # public signature
        dashboard: bool = True, watch: bool = True,
        stop: threading.Event | None = None, on_ready=None) -> None:
    """Run dashboard, worker and watcher until `stop`; RunError if one of them crashes."""
    stop = stop or threading.Event()
    lock = _Lock(Path(cfg.home))
    threads = _Threads(stop)
    server = None
    serve_started = False
    main_svc = None
    try:
        main_svc = build(cfg)
        info: dict[str, object] = {"port": None, "token": None, "url": None}
        if dashboard:
            server = _make_dashboard(main_svc, port)
            info["port"], info["token"] = server.server_address[1], server.token
            info["url"] = f"http://127.0.0.1:{info['port']}/?token={server.token}"
        live: list = []
        if server:  # a settings save swaps the model registry of the worker too, no restart
            server.listeners.append(lambda reg: [setattr(x, "registry", reg) for x in list(live)])
        starts = [threads.add("worker", lambda conns: _worker(cfg, stop, conns, live))]
        if watch:
            starts.append(threads.add("watcher", lambda conns: _watcher(cfg, stop, conns)))
        if server:
            starts.append(threads.add("dashboard", lambda conns: server.serve_forever()))
        for t in starts:
            t.start()
            if t.name == "dashboard":
                serve_started = True
        if on_ready:
            on_ready(info)
        stop.wait()
    finally:
        stop.set()
        if server is not None:
            if serve_started:
                server.shutdown()
            server.server_close()
        threads.join_all()
        if main_svc is not None:
            main_svc.conn.close()
        lock.release()
    if threads.crashed:
        raise RunError(
            f"{', '.join(threads.crashed)} thread crashed (see traceback above); shutting down")
