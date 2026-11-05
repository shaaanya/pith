"""--home / --config must work before AND after the subcommand, for every subcommand.

Every subprocess runs with HOME and INFOPARSER_HOME pointed into tmp_path, so a regression
can never touch the real ~/InfoParser; the (fake) default home must stay absent.
"""
import os
import subprocess
import sys

import pytest

from infoparser import cli

# (argv after the subcommand-independent flags, creates the database in the flagged home)
RUNNABLE = [
    (["init"], True),
    (["inbox"], True),
    (["search", "nothing"], True),
    (["export"], True),
    (["digest", "--dry-run"], True),
    (["reindex"], True),
    (["worker", "--once"], True),
    (["watch", "--once"], True),
    (["import-telegram", "missing.json"], True),
    (["doctor"], False),
    (["egress"], False),
    (["adapters", "list"], False),
]
# every subcommand with minimal valid arguments (parse-level coverage; nothing is executed)
ALL = [["init"], ["submit", "x"], ["inbox"], ["retry", "i"], ["worker"], ["search", "q"],
       ["ask", "q"], ["show", "i"], ["reindex"], ["doctor"], ["egress"], ["export"],
       ["backup"], ["restore", "a.tgz"], ["verify", "a.tgz"], ["digest"], ["adapters", "list"],
       ["adapters", "run", "fs"], ["watch"], ["import-telegram", "p"], ["serve-http"],
       ["run"], ["dashboard"]]


def _run(tmp_path, argv, extra_env=None):
    fake_home = tmp_path / "fakehome"
    fake_home.mkdir(exist_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith("INFOPARSER_")}
    env.update({"HOME": str(fake_home), "INFOPARSER_HOME": str(tmp_path / "envhome"),
                **(extra_env or {})})
    return subprocess.run([sys.executable, "-m", "infoparser.cli", *argv], env=env,
                          capture_output=True, text=True, timeout=60, check=False)


def _flag_args(kind, position, tmp_path, cmd):
    target = tmp_path / "flagged"
    if kind == "home":
        flag, home = ["--home", str(target)], target
    else:
        conf = tmp_path / "c.toml"
        conf.write_text(f'home = "{target}"\n')
        flag, home = ["--config", str(conf)], target
    argv = [*flag, *cmd] if position == "before" else [cmd[0], *flag, *cmd[1:]]
    return argv, home


@pytest.mark.parametrize("position", ["before", "after"])
@pytest.mark.parametrize("kind", ["home", "config"])
@pytest.mark.parametrize("cmd,creates_db", RUNNABLE)
def test_flag_selects_home_in_either_position(tmp_path, cmd, creates_db, kind, position):
    """Flag home is used, defaults and env home untouched."""
    argv, home = _flag_args(kind, position, tmp_path, cmd)
    # an empty env var means "unset" to load_config's `or`, so the config file's home applies
    extra = {"INFOPARSER_HOME": ""} if kind == "config" else None
    res = _run(tmp_path, argv, extra)
    assert "Traceback" not in res.stderr, res.stderr
    assert not (tmp_path / "fakehome" / "InfoParser").exists(), "touched the default home"
    if kind == "home":
        assert not (tmp_path / "envhome").exists(), "flag lost to the env home"
    if creates_db:
        assert (home / "infoparser.db").exists(), res.stdout + res.stderr


@pytest.mark.parametrize("cmd", ALL)
@pytest.mark.parametrize("position", ["before", "after"])
def test_parser_accepts_flags_for_every_subcommand(cmd, position):
    """Both flags parse for every subcommand in both positions."""
    flags = ["--home", "/h", "--config", "/c.toml"]
    argv = [*flags, *cmd] if position == "before" else [*cmd[:1], *flags, *cmd[1:]]
    if cmd[0] == "adapters":  # flags after the nested subcommand too
        argv = [cmd[0], *cmd[1:], *flags] if position == "after" else argv
    args = cli.build_parser().parse_args(argv)
    assert (cli.resolved(args, "home"), cli.resolved(args, "config")) == ("/h", "/c.toml")


def test_subcommand_position_wins_and_default_is_none():
    """Subcommand position beats top-level; absent flags resolve to None."""
    parser = cli.build_parser()
    both = parser.parse_args(["--home", "/a", "init", "--home", "/b"])
    assert cli.resolved(both, "home") == "/b"
    none = parser.parse_args(["init"])
    assert cli.resolved(none, "home") is None and cli.resolved(none, "config") is None


def test_env_home_used_without_flag_and_flag_beats_env(tmp_path):
    """Env home applies without a flag; an explicit flag overrides it."""
    res = _run(tmp_path, ["init"])
    assert (tmp_path / "envhome" / "infoparser.db").exists(), res.stderr
    res = _run(tmp_path, ["--home", str(tmp_path / "flagged"), "init"])
    assert (tmp_path / "flagged" / "infoparser.db").exists(), res.stderr
