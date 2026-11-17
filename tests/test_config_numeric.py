"""Numeric config values are validated at load (limitations triage)."""
import os
import subprocess
import sys

import pytest

from pith.config import ConfigError, load_config


def _load(tmp_path, toml):
    path = tmp_path / "c.toml"
    path.write_text(toml, encoding="utf-8")
    return load_config(path, env={"PITH_HOME": str(tmp_path / "h")})


@pytest.mark.parametrize("section,key", [
    ("limits", "max_attempts"), ("limits", "lease_seconds"), ("limits", "max_fetch_bytes"),
    ("http", "port"), ("digest", "interval_days"), ("digest", "max_items")])
@pytest.mark.parametrize("bad", ['"abc"', "5.5", "true", "[1]", "-1"])
def test_bad_numeric_config_raises_configerror(tmp_path, section, key, bad):
    """A wrong-typed or negative number fails at load with a message naming the key."""
    with pytest.raises(ConfigError, match=f"{section}.{key}"):
        _load(tmp_path, f"[{section}]\n{key} = {bad}\n")


def test_zero_limits_are_refused_and_quoted_digits_coerced(tmp_path):
    """0 would make jobs never run; a quoted integer is coerced rather than crashing later."""
    with pytest.raises(ConfigError, match="limits.max_attempts"):
        _load(tmp_path, "[limits]\nmax_attempts = 0\n")
    cfg = _load(tmp_path,
                '[limits]\nmax_attempts = "7"\nlease_seconds = 9\nmax_fetch_bytes = "1000"\n')
    assert (cfg.max_attempts, cfg.lease_seconds, cfg.max_fetch_bytes) == (7, 9, 1000)


def test_cli_reports_bad_config_cleanly(tmp_path):
    """The CLI prints one error line instead of a traceback."""
    path = tmp_path / "c.toml"
    path.write_text('[limits]\nmax_attempts = "x"\n', encoding="utf-8")
    env = {**os.environ, "PITH_HOME": str(tmp_path / "h")}
    res = subprocess.run([sys.executable, "-m", "pith.cli", "--config", str(path), "inbox"],
                         env=env, check=False, capture_output=True, text=True, timeout=60)
    assert res.returncode != 0 and "Traceback" not in res.stderr
    assert "limits.max_attempts" in res.stderr


@pytest.mark.parametrize("exotic", ["²", "٣", "①"])
def test_exotic_unicode_digits_raise_configerror_not_valueerror(tmp_path, exotic):
    """str.isdigit() accepts superscripts and non-ASCII digits that int() rejects."""
    with pytest.raises(ConfigError, match="http.port"):
        _load(tmp_path, f'[http]\nport = "{exotic}"\n')
