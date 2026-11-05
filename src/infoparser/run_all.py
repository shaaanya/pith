"""`infoparser run`: dashboard + worker loop + fs watcher in one process, clean shutdown.

One `run` per home: <home>/run.lock is held with flock (released by the OS if we die, so no stale-lock or PID-reuse
races); the PID inside is only for the error message. Each thread owns its SQLite connection. A thread that
crashes prints its traceback to stderr and stops the whole run (RunError), so the dashboard never keeps
serving a dead worker. Not included: http ingest (use `infoparser serve-http`)."""
from __future__ import annotations

import fcntl
import os
import sys
import threading
import traceback
from pathlib import Path

from infoparser.services import build

JOIN_SECONDS = 30


class RunError(Exception):
    pass


class _Lock:
    def __init__(self, home: Path):
        home.mkdir(parents=True, exist_ok=True)
        self.path = home / "run.lock"
        self.f = open(self.path, "a+")
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
        self.path.unlink(missing_ok=True)  # while still holding the lock
        self.f.close()


def run(cfg, port: int = 8777, *, dashboard: bool = True, watch: bool = True,
        stop: threading.Event | None = None, on_ready=None) -> None:
    from infoparser.adapters.fs import FsAdapter
    from infoparser.dashboard.server import make_server
    from infoparser.pipeline import runner
    from infoparser.worker import Worker

    stop = stop or threading.Event()
    lock = _Lock(Path(cfg.home))
    threads: list[tuple[threading.Thread, list]] = []  # (thread, [its connections])
    crashed: list[str] = []
    server = None
    serve_started = False
    main_svc = None
    try:
        main_svc = build(cfg)
        info = {"port": None, "token": None, "url": None}
        if dashboard:
            try:
                server = make_server(main_svc, port=port)
            except OSError as e:
                raise RunError(f"port {port} in use or unavailable: {e}") from e
            info["port"], info["token"] = server.server_address[1], server.token
            info["url"] = f"http://127.0.0.1:{info['port']}/?token={server.token}"

        def guarded(name, fn):
            conns: list = []

            def target():
                try:
                    fn(conns)
                except BaseException:  # noqa: BLE001 - a dead thread must take the whole run down, loudly
                    traceback.print_exc()
                    crashed.append(name)
                    stop.set()
            t = threading.Thread(target=target, name=name)
            threads.append((t, conns))
            return t

        def worker(conns):
            s = build(cfg)
            conns.append(s.conn)
            Worker(s.conn, s.inbox, s.queue, lambda i: runner.process(s, i), worker_id="run").run_forever(0.5, stop)

        def watcher(conns):
            s = build(cfg)
            conns.append(s.conn)
            FsAdapter(s.inbox, s.cfg.watch_dirs).run_forever(5.0, stop)

        starts = [guarded("worker", worker)] + ([guarded("watcher", watcher)] if watch else [])
        if server:
            starts.append(guarded("dashboard", lambda conns: server.serve_forever()))
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
        for t, conns in threads:
            if not t.is_alive() and not t.ident:
                continue
            t.join(JOIN_SECONDS)
            if t.is_alive():
                print(f"warning: thread {t.name} did not stop within {JOIN_SECONDS}s; leaving its connection open",
                      file=sys.stderr)
                continue
            for c in conns:
                c.close()
        if main_svc is not None:
            main_svc.conn.close()
        lock.release()
    if crashed:
        raise RunError(f"{', '.join(crashed)} thread crashed (see traceback above); shutting down")
