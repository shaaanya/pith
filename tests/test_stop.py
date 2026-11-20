"""Cooperative shutdown uses instance identity and actual completion, never saved PIDs."""
import fcntl
import json
import os
import select
import signal
import subprocess
import sys
import threading

import pytest

from pith import cli, run_all, run_control
from pith.config import load_config, resolve_home


def env_for(home):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("PITH_", "INFOPARSER_"))}
    return {**env, "PITH_HOME": str(home), "HOME": str(home.parent / "user")}


def start(home, *, dashboard=True):
    args = [sys.executable, "-m", "pith.cli", "run", "--no-watch", "--no-open", "--port", "0"]
    if not dashboard:
        args.append("--no-dashboard")
    process = subprocess.Popen(args, env=env_for(home), stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True)
    try:
        assert select.select([process.stdout], [], [], 15)[0], "run did not become ready"
        line = process.stdout.readline()
        assert line.startswith("dashboard:" if dashboard else "running (no dashboard)"), line
        return process
    except BaseException:
        finish(process)
        raise


def finish(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(5)
    process.stdout.close()
    process.stderr.close()


def command(home, *args):
    return subprocess.run([sys.executable, "-m", "pith.cli", *args], env=env_for(home),
                          capture_output=True, text=True, timeout=15, check=False)


@pytest.mark.parametrize("dashboard", [True, False])
def test_stop_real_cli_run_and_repeat_without_dashboard_dependency(tmp_path, dashboard):
    home = tmp_path / "home"
    process = start(home, dashboard=dashboard)
    try:
        result = command(home, "stop", "--timeout", "5")
        assert result.returncode == 0, result.stderr
        assert result.stdout.startswith("stopped:")
        assert process.wait(5) == 0, process.stderr.read()
        again = command(home, "stop")
        assert again.returncode == 0 and again.stdout.startswith("not running:")
        assert not list(home.glob("run.stop-*"))
        assert not (home / "run.lock").read_text()
    finally:
        finish(process)


def test_wrong_home_and_stale_pid_never_signal_an_unrelated_process(tmp_path):
    home = tmp_path / "home"
    process = start(home, dashboard=False)
    wrong = tmp_path / "wrong"
    try:
        result = command(wrong, "stop")
        assert result.returncode == 0 and "not running" in result.stdout
        assert not wrong.exists()
        wrong.mkdir()
        (wrong / "run.lock").write_text(str(process.pid))
        assert command(wrong, "stop").returncode == 0
        assert process.poll() is None
    finally:
        finish(process)


def test_stale_generation_request_cannot_stop_a_new_run(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    old = home / ("run.stop-" + "0" * 32)
    old.write_text("old request")
    process = start(home, dashboard=False)
    try:
        current = json.loads((home / "run.lock").read_text())["instance"]
        assert current != "0" * 32
        assert process.poll() is None
        assert run_control.stop(home, 5)
        assert process.wait(5) == 0
    finally:
        finish(process)


def test_late_request_does_not_stop_a_replacement_instance(tmp_path, monkeypatch):
    original = run_control.RunLock(tmp_path)
    replacement = []
    write = run_control._write_request

    def replace_between_observation_and_request(home, instance):
        original.release()
        replacement.append(run_control.RunLock(home))
        write(home, instance)
    monkeypatch.setattr(run_control, "_write_request", replace_between_observation_and_request)
    try:
        assert run_control.stop(tmp_path, 1)
        assert not replacement[0].stop_requested()
    finally:
        replacement[0].release()


def test_timeout_during_busy_shutdown_retains_lock_until_worker_finishes(tmp_path, monkeypatch, capsys):
    cfg = load_config(env={"PITH_HOME": str(tmp_path / "home")})
    release, ready = threading.Event(), threading.Event()
    errors = []
    monkeypatch.setattr(run_all, "JOIN_SECONDS", 0.02)
    monkeypatch.setattr(run_all, "_worker", lambda *_: release.wait())

    def run():
        try:
            run_all.run(cfg, dashboard=False, watch=False, on_ready=lambda _: ready.set())
        except BaseException as error:  # noqa: BLE001
            errors.append(error)
    thread = threading.Thread(target=run)
    thread.start()
    try:
        assert ready.wait(5)
        with pytest.raises(run_control.RunError, match="still stopping"):
            run_control.stop(cfg.home, 0.3)
        assert thread.is_alive()
        with pytest.raises(run_all.RunError, match="already running"):
            run_all.run(cfg, dashboard=False, watch=False)
        assert "waiting for active work" in capsys.readouterr().err
    finally:
        release.set()
        thread.join(5)
    assert not thread.is_alive() and not errors
    assert run_control.stop(cfg.home) is False


def test_stop_resolves_known_home_despite_broken_config(tmp_path):
    home = tmp_path / "home"
    process = start(home, dashboard=False)
    try:
        (home / "config.toml").write_text("invalid TOML [[[")
        result = command(home, "stop", "--home", str(home))
        assert result.returncode == 0, result.stderr
        assert process.wait(5) == 0
        assert command(home, "stop").returncode == 0  # PITH_HOME works too
    finally:
        finish(process)


def test_stop_config_only_reads_home_and_explains_bad_toml(tmp_path):
    config = tmp_path / "c.toml"
    home = tmp_path / "selected"
    config.write_text(f'home = "{home}"\n[limits]\nmax_attempts = "invalid"\n')
    assert resolve_home(config, {}) == home
    result = command(tmp_path / "ignored", "stop", "--home", str(home), "--config", str(config))
    assert result.returncode == 0 and "not running" in result.stdout
    assert not home.exists()
    config_only = subprocess.run(
        [sys.executable, "-m", "pith.cli", "stop", "--config", str(config)],
        env={**env_for(tmp_path / "ignored"), "PITH_HOME": ""},
        capture_output=True, text=True, timeout=10, check=False)
    assert config_only.returncode == 0 and str(home) in config_only.stdout
    assert not home.exists()
    config.write_text("invalid [[[")
    with pytest.raises(ValueError, match="use `pith stop --home PATH`"):
        resolve_home(config, {})


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf"])
def test_invalid_stop_timeout_is_a_clean_cli_error(tmp_path, value):
    result = command(tmp_path / "home", "stop", f"--timeout={value}")
    assert result.returncode != 0 and "--timeout" in result.stderr
    assert "Traceback" not in result.stderr
    assert not (tmp_path / "home").exists()


def test_locked_legacy_pid_is_not_signalled(tmp_path, monkeypatch):
    with open(tmp_path / "run.lock", "w+") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        held.write(str(os.getpid()))
        held.flush()
        monkeypatch.setattr(os, "kill", lambda *_: pytest.fail("saved PIDs must never be signalled"))
        with pytest.raises(run_control.RunError, match="Ctrl-C"):
            run_control.stop(tmp_path, 0.1)


def test_run_signals_request_shutdown_and_restore_handlers(tmp_path, monkeypatch):
    cfg = load_config(env={"PITH_HOME": str(tmp_path / "home")})
    previous = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
    monkeypatch.setattr(cli, "_cfg", lambda _: cfg)

    def run(_cfg, _port, **kwargs):
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGINT):
            signal.raise_signal(sig)
            assert kwargs["stop"].is_set()
    monkeypatch.setattr(run_all, "run", run)
    cli.main(["run", "--no-dashboard", "--no-watch", "--no-open"])
    assert {sig: signal.getsignal(sig) for sig in previous} == previous


def test_unreadable_metadata_and_symlink_lock_fail_without_following(tmp_path):
    lock = tmp_path / "run.lock"
    with open(lock, "wb") as held:
        held.write(b"\xff\xfe")
        held.flush()
        fcntl.flock(held, fcntl.LOCK_EX)
        with pytest.raises(run_control.RunError, match="no shutdown metadata"):
            run_control.stop(tmp_path, 0.1)
    lock.unlink()
    unrelated = tmp_path / "unrelated"
    unrelated.write_text("leave this alone")
    lock.symlink_to(unrelated)
    with pytest.raises(run_control.RunError, match="cannot open run lock"):
        run_control.stop(tmp_path)
    assert unrelated.read_text() == "leave this alone"
