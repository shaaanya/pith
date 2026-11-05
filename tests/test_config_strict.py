"""Config shapes are validated at load; every ConfigError is one clean CLI line."""
import os
import subprocess
import sys

import pytest

from infoparser.config import ConfigError, load_config


def _load(tmp_path, toml):
    path = tmp_path / "c.toml"
    path.write_text(toml, encoding="utf-8")
    return load_config(path, env={"INFOPARSER_HOME": str(tmp_path / "h")})


@pytest.mark.parametrize("bad", ['"false"', '"no"', "0", "1", "[]"])
def test_allow_remote_must_be_a_real_boolean(tmp_path, bad):
    """bool('false') is True: a quoted value must never switch remote egress on."""
    with pytest.raises(ConfigError, match="privacy.allow_remote"):
        _load(tmp_path, f"[privacy]\nallow_remote = {bad}\n")


def test_allow_remote_true_false_accepted(tmp_path):
    """Real booleans still load."""
    assert _load(tmp_path, "[privacy]\nallow_remote = true\n").allow_remote is True
    assert _load(tmp_path, "[privacy]\nallow_remote = false\n").allow_remote is False


@pytest.mark.parametrize("bad", ['"~/Drop"', "5", "[1]", "[\"a\", 2]"])
def test_watch_dirs_must_be_a_list_of_strings(tmp_path, bad):
    """A string would be iterated per character (home and / watched)."""
    with pytest.raises(ConfigError, match="watch.dirs"):
        _load(tmp_path, f"[watch]\ndirs = {bad}\n")


@pytest.mark.parametrize("toml,needle", [
    ("home = 5\n", "home"),
    ("[tasks]\nx = 5\n", "tasks.x"),
    ("[tasks]\nx = [1]\n", "tasks.x"),
    ("[http]\nbind = 5\n", "http.bind"),
    ("[backends]\nx = 5\n", "backends.x"),
])
def test_wrong_shapes_raise_configerror(tmp_path, toml, needle):
    """Wrong-typed values raise ConfigError instead of TypeError."""
    with pytest.raises(ConfigError, match=needle):
        _load(tmp_path, toml)


def test_bad_toml_raises_configerror(tmp_path):
    """Syntax errors are configuration errors."""
    with pytest.raises(ConfigError, match="c.toml"):
        _load(tmp_path, "this is = = not toml\n")


def test_missing_config_file_raises_configerror(tmp_path):
    """--config pointing nowhere is a configuration error."""
    with pytest.raises(ConfigError, match="nope.toml"):
        load_config(tmp_path / "nope.toml", env={})


def _cli(tmp_path, toml, *argv):
    path = tmp_path / "c.toml"
    if toml is not None:
        path.write_text(toml, encoding="utf-8")
    env = {**os.environ, "INFOPARSER_HOME": str(tmp_path / "h")}
    return subprocess.run([sys.executable, "-m", "infoparser.cli", "--config", str(path), *argv],
                          env=env, check=False, capture_output=True, text=True, timeout=60)


@pytest.mark.parametrize("toml", [
    None,
    "not = = toml",
    "[tasks]\nx = 5\n",
    "home = 5\n",
    '[privacy]\nallow_remote = "false"\n',
    '[watch]\ndirs = "~/Drop"\n',
    '[backends.x]\ntype = "nope"\n',
    '[backends.x]\ntype = "heuristic"\n[tasks]\ndistill = "ghost"\n',
])
@pytest.mark.parametrize("argv", [("inbox",), ("doctor",), ("worker", "--once"), ("search", "q")])
def test_every_bad_config_is_one_clean_error_line(tmp_path, toml, argv):
    """No traceback, non-zero exit, an `error:` line, for every command."""
    res = _cli(tmp_path, toml, *argv)
    assert res.returncode != 0
    assert "Traceback" not in res.stderr
    # doctor reports an unbuildable registry as its own ERROR line on stdout
    assert "error:" in res.stderr or (argv[0] == "doctor" and "ERROR" in res.stdout)
