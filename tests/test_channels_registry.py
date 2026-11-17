"""[channels.*] config, the channel registry, and `pith run` starting channel threads."""
import os
import threading
import time

import pytest

from pith import run_all
from pith.adapters import build_channel, enabled_channels
from pith.adapters.base import ChannelState
from pith.config import ConfigError, load_config
from pith.services import build


def mkcfg(tmp_path, toml=""):
    f = tmp_path / "c.toml"
    f.write_text(toml)
    return load_config(f, env={"PITH_HOME": str(tmp_path / "home")})


def test_channels_table_parsed_and_validated(tmp_path):
    cfg = mkcfg(tmp_path, "[channels.telegram]\nenabled = true\nallowed_chat_ids = [1]\n")
    assert cfg.channels["telegram"]["allowed_chat_ids"] == [1]
    with pytest.raises(ConfigError):
        mkcfg(tmp_path, "[channels]\nfs = 3\n")
    with pytest.raises(ConfigError):
        mkcfg(tmp_path, "[channels.fs]\nenabled = \"yes\"\n")


def test_fs_enabled_by_default_and_can_be_disabled(tmp_path):
    assert enabled_channels(mkcfg(tmp_path)) == ["fs"]
    assert enabled_channels(mkcfg(tmp_path, "[channels.fs]\nenabled = false\n")) == []


def test_telegram_needs_enabled_true(tmp_path):
    assert enabled_channels(mkcfg(tmp_path, "[channels.telegram]\nenabled = false\n")) == ["fs"]
    assert enabled_channels(mkcfg(tmp_path, "[channels.telegram]\nchat = 1\n")) == ["fs"]
    assert enabled_channels(mkcfg(tmp_path, "[channels.telegram]\nenabled = true\n")) == ["fs", "telegram"]


def test_unknown_channel_is_a_clear_error(svc):
    with pytest.raises(ValueError, match="unknown channel"):
        build_channel("carrier-pigeon", svc)


def test_build_fs_channel_polls_dropped_file(tmp_path):
    cfg = mkcfg(tmp_path)
    svc = build(cfg)
    ch = build_channel("fs", svc)
    assert ch.name == "fs" and ch.interval == 5.0
    cfg.watch_dirs[0].mkdir(parents=True)
    p = cfg.watch_dirs[0] / "note.txt"
    p.write_text("a dropped note about quokkas")
    os.utime(p, (time.time() - 10, time.time() - 10))
    ch.poll()
    assert ch.poll() == 1
    assert len(svc.inbox.list()) == 1


def test_fs_interval_is_configurable(tmp_path):
    svc = build(mkcfg(tmp_path, "[channels.fs]\ninterval = 0.1\n"))
    assert build_channel("fs", svc).interval == 0.1


def test_enabled_telegram_without_token_does_not_kill_the_run(tmp_path, monkeypatch):
    monkeypatch.delenv("PITH_TELEGRAM_TOKEN", raising=False)
    cfg = mkcfg(tmp_path, "[channels.telegram]\nenabled = true\n")
    stop, ready, err = threading.Event(), threading.Event(), []

    def go():
        try:
            run_all.run(cfg, port=0, dashboard=False, stop=stop, on_ready=lambda i: ready.set())
        except BaseException as e:  # noqa: BLE001
            err.append(e)
            ready.set()
    t = threading.Thread(target=go)
    t.start()
    assert ready.wait(15)
    s = build(cfg)
    try:
        end = time.time() + 15
        while time.time() < end and not ChannelState(s.conn, "telegram").get("last_error"):
            time.sleep(0.1)
        assert "telegram_token" in (ChannelState(s.conn, "telegram").get("last_error") or "")
        assert t.is_alive() and not err  # the run (dashboard, worker) survives a channel error
    finally:
        stop.set()
        t.join(30)
        s.conn.close()
    assert not t.is_alive() and not err


def test_run_all_runs_channels_and_records_status(tmp_path):
    cfg = mkcfg(tmp_path, "[channels.fs]\ninterval = 0.1\n")
    cfg.watch_dirs[0].mkdir(parents=True)
    p = cfg.watch_dirs[0] / "note.txt"
    p.write_text("a dropped note about quokkas")
    os.utime(p, (time.time() - 10, time.time() - 10))
    stop, ready, err = threading.Event(), threading.Event(), []

    def go():
        try:
            run_all.run(cfg, port=0, dashboard=False, stop=stop, on_ready=lambda i: ready.set())
        except BaseException as e:  # noqa: BLE001
            err.append(e)
            ready.set()
    t = threading.Thread(target=go)
    t.start()
    assert ready.wait(15)
    s = build(cfg)
    try:
        end = time.time() + 20
        while time.time() < end and ChannelState(s.conn, "fs").get("submitted") != "1":
            time.sleep(0.1)
        assert ChannelState(s.conn, "fs").get("submitted") == "1"
        assert ChannelState(s.conn, "fs").get("last_ok_at")
    finally:
        stop.set()
        t.join(30)
        s.conn.close()
    assert not t.is_alive() and not err
