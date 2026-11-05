import json
import os
import threading
import time
import urllib.request

import pytest

from infoparser import run_all
from infoparser.adapters.http_ingest import load_token
from infoparser.config import load_config

NOTE = "Quokkas are small marsupials from Australia.\n\nThey live on Rottnest Island and eat grass."


def start(cfg, **kw):
    stop, info = threading.Event(), {}
    ready = threading.Event()

    def on_ready(i):
        info.update(i)
        ready.set()
    err = []

    def go():
        try:
            run_all.run(cfg, port=0, stop=stop, on_ready=on_ready, **kw)
        except BaseException as e:  # noqa: BLE001
            err.append(e)
            ready.set()
    t = threading.Thread(target=go)
    t.start()
    assert ready.wait(15)
    return stop, t, info, err


def call(info, method, path, body=None):
    req = urllib.request.Request(f"http://127.0.0.1:{info['port']}{path}", method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"X-Token": info["token"], "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


@pytest.fixture
def cfg(tmp_path):
    return load_config(env={"INFOPARSER_HOME": str(tmp_path / "home")})


def wait_for(fn, secs=20):
    end = time.time() + secs
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.1)
    raise AssertionError("timeout")


def test_run_processes_submission_in_background(cfg):
    stop, t, info, err = start(cfg)
    try:
        out = call(info, "POST", "/api/inbox", {"text": NOTE, "context": "animals"})
        wait_for(lambda: call(info, "GET", f"/api/inbox/{out['id']}")["status"] == "processed")
        hits = call(info, "GET", "/api/search?q=quokkas")["hits"]
        assert hits
        item = call(info, "GET", f"/api/items/{hits[0]['item_id']}")
        assert item["provenance"] in ("stated", "inferred", "external") and item["source"]["id"]
        # failed -> retry works end to end
        from infoparser.services import build
        s = build(cfg)
        s.inbox.set_status(out["id"], "failed", "boom")
        assert call(info, "POST", f"/api/inbox/{out['id']}/retry", {})["ok"]
        wait_for(lambda: call(info, "GET", f"/api/inbox/{out['id']}")["status"] == "processed")
        s.conn.close()
    finally:
        stop.set()
        t.join(30)
    assert not t.is_alive() and not err
    assert _lock_free(cfg)
    with pytest.raises(OSError):
        urllib.request.urlopen(f"http://127.0.0.1:{info['port']}/", timeout=2)


def test_second_run_same_home_is_a_clear_error(cfg):
    stop, t, info, err = start(cfg)
    try:
        with pytest.raises(run_all.RunError, match="already running"):
            run_all.run(cfg, port=0, stop=threading.Event())
    finally:
        stop.set()
        t.join(30)


def _lock_free(cfg) -> bool:
    import fcntl
    with open(cfg.home / "run.lock", "a+") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        return True


def test_stale_lock_is_taken_over(cfg):
    cfg.home.mkdir(parents=True, exist_ok=True)
    (cfg.home / "run.lock").write_text("999999999")
    stop, t, info, err = start(cfg)
    stop.set()
    t.join(30)
    assert not err


def test_port_in_use_is_a_clear_error(cfg, tmp_path):
    import socket
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen()
    try:
        with pytest.raises(run_all.RunError, match="port .* in use"):
            run_all.run(cfg, port=sock.getsockname()[1], stop=threading.Event())
    finally:
        sock.close()
    assert _lock_free(cfg)  # lock released on failed start


def test_no_dashboard_and_no_watch_flags(cfg):
    stop, t, info, err = start(cfg, dashboard=False, watch=False)
    assert info["port"] is None
    stop.set()
    t.join(30)
    assert not err


def test_crashed_worker_stops_the_process_loudly(cfg, monkeypatch, capsys):
    from infoparser.worker import Worker

    def boom(self):
        raise RuntimeError("worker exploded")
    monkeypatch.setattr(Worker, "run_once", boom)
    err = []

    def go():
        try:
            run_all.run(cfg, port=0, watch=False)
        except BaseException as e:  # noqa: BLE001
            err.append(e)
    t = threading.Thread(target=go, daemon=True)
    t.start()
    t.join(15)
    assert not t.is_alive(), "run() kept serving a dead worker"
    assert err and isinstance(err[0], run_all.RunError) and "worker" in str(err[0])
    assert "worker exploded" in capsys.readouterr().err
    assert _lock_free(cfg)  # the crashed run released its flock (file itself is persistent)


def test_lock_is_a_real_flock_not_just_a_pid_file(cfg):
    import fcntl
    cfg.home.mkdir(parents=True, exist_ok=True)
    held = open(cfg.home / "run.lock", "a+")
    fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
    held.seek(0)
    held.truncate()
    held.write("1")  # PID 1 is alive, but the point is the flock
    held.flush()
    try:
        with pytest.raises(run_all.RunError, match="already running"):
            run_all.run(cfg, port=0, stop=threading.Event())
    finally:
        held.close()
