"""`pith run`: dashboard + worker loop + one thread per enabled channel in one process, clean shutdown.

One `run` per home: <home>/run.lock is held with flock (released by the OS if we die, so no
stale-lock or PID-reuse races); metadata also identifies cooperative stop requests. Each thread owns
its SQLite connection. A thread that crashes prints its traceback to stderr and stops the whole
run (RunError), so the dashboard never keeps serving a dead worker. Not included: http ingest
(use `pith serve-http`)."""
from __future__ import annotations

import sys
import threading
import traceback
from pathlib import Path

from pith.adapters import build_channel, enabled_channels
from pith.adapters.base import ChannelState, run_channel
from pith.dashboard.server import make_server
from pith.pipeline import runner
from pith.services import build
from pith.run_control import POLL_SECONDS, RunError, RunLock as _Lock
from pith.worker import Worker

JOIN_SECONDS = 30


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
                      "waiting for active work to finish", file=sys.stderr)
                # Keep run.lock until shutdown is real. `pith stop` can time out
                # without falsely reporting success or admitting a second worker.
                t.join()
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


def _channel(cfg, stop, conns, name) -> None:
    """Thread body: run channel `name` with its own connection until `stop`."""
    s = build(cfg)
    conns.append(s.conn)
    run_channel(build_channel(name, s), ChannelState(s.conn, name), stop)


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
            for name in enabled_channels(cfg):
                starts.append(threads.add(
                    f"channel:{name}", lambda conns, n=name: _channel(cfg, stop, conns, n)))
        if server:
            starts.append(threads.add("dashboard", lambda conns: server.serve_forever()))
        for t in starts:
            t.start()
            if t.name == "dashboard":
                serve_started = True
        if on_ready:
            on_ready(info)
        while not stop.wait(POLL_SECONDS):
            if lock.stop_requested():
                stop.set()
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
