"""`infoparser run`: dashboard + worker loop + fs watcher in one process, clean shutdown.

One `run` per home: <home>/run.lock holds the PID (stale locks from dead PIDs are taken over).
Each thread owns its SQLite connection. Not included: http ingest (use `infoparser serve-http`)."""
from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

from infoparser.services import build

JOIN_SECONDS = 30


class RunError(Exception):
    pass


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _acquire(home: Path) -> Path:
    home.mkdir(parents=True, exist_ok=True)
    lock = home / "run.lock"
    for _ in range(2):
        try:
            fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            try:
                pid = int(lock.read_text().strip() or 0)
            except (ValueError, OSError):
                pid = 0
            if pid and _alive(pid):
                raise RunError(f"already running for {home} (pid {pid}); stop it first")
            lock.unlink(missing_ok=True)  # stale
            continue
        with os.fdopen(fd, "w") as f:
            f.write(str(os.getpid()))
        return lock
    raise RunError(f"could not acquire {lock}")


def run(cfg, port: int = 8777, *, dashboard: bool = True, watch: bool = True,
        stop: threading.Event | None = None, on_ready=None) -> None:
    from infoparser.adapters.fs import FsAdapter
    from infoparser.dashboard.server import make_server
    from infoparser.pipeline import runner
    from infoparser.worker import Worker

    stop = stop or threading.Event()
    lock = _acquire(Path(cfg.home))
    threads: list[threading.Thread] = []
    conns = []
    server = None
    try:
        main_svc = build(cfg)
        conns.append(main_svc.conn)
        info = {"port": None, "token": None, "url": None}
        if dashboard:
            try:
                server = make_server(main_svc, port=port)
            except OSError as e:
                raise RunError(f"port {port} in use or unavailable: {e}") from e
            info["port"] = server.server_address[1]
            info["token"] = server.token
            info["url"] = f"http://127.0.0.1:{info['port']}/?token={server.token}"

        def worker():
            s = build(cfg)
            conns.append(s.conn)
            Worker(s.conn, s.inbox, s.queue, lambda i: runner.process(s, i), worker_id="run").run_forever(0.5, stop)

        def watcher():
            s = build(cfg)
            conns.append(s.conn)
            FsAdapter(s.inbox, s.cfg.watch_dirs).run_forever(5.0, stop)

        targets = [worker] + ([watcher] if watch else []) + ([server.serve_forever] if server else [])
        for fn in targets:
            t = threading.Thread(target=fn, name=getattr(fn, "__name__", "dashboard"))
            t.start()
            threads.append(t)
        if on_ready:
            on_ready(info)
        stop.wait()
    finally:
        stop.set()
        if server:
            server.shutdown() if any(t.is_alive() for t in threads) else None
            server.server_close()
        for t in threads:
            t.join(JOIN_SECONDS)
            if t.is_alive():
                print(f"warning: thread {t.name} did not stop within {JOIN_SECONDS}s", file=sys.stderr)
        for c in conns:
            try:
                c.close()
            except Exception:  # noqa: BLE001
                pass
        lock.unlink(missing_ok=True)
