"""`pith setup`: the interactive channel setup (token, enable, pairing code)."""
import os
import stat
import subprocess
import sys

import pytest
from stubs.fake_telegram import FakeTelegram

from pith.adapters.setup import run_setup
from pith.config import load_config


@pytest.fixture(name="fake")
def fake_fixture():
    with FakeTelegram() as f:
        yield f


class Script:
    """Scripted answers; collects what the flow prints."""

    def __init__(self, answers, secrets):
        self.answers, self.secrets, self.lines = list(answers), list(secrets), []

    def input(self, _prompt=""):
        return self.answers.pop(0)

    def secret(self, _prompt=""):
        return self.secrets.pop(0)

    def out(self, text=""):
        self.lines.append(str(text))

    @property
    def text(self):
        return "\n".join(self.lines)


def go(svc, fake, answers, secrets, api_base=None):
    sc = Script(answers, secrets)
    rc = run_setup(svc, input_fn=sc.input, secret_fn=sc.secret, out=sc.out,
                   api_base=api_base or fake.url)
    return rc, sc


def enabled(svc):
    if not (svc.cfg.home / "config.toml").exists():
        return False
    cfg = load_config(svc.cfg.home / "config.toml", {"PITH_HOME": str(svc.cfg.home)})
    return cfg.channels.get("telegram", {}).get("enabled") is True


def code_of(svc):
    r = svc.conn.execute("SELECT value FROM channel_state WHERE channel='telegram'"
                         " AND key='pairing_code'").fetchone()
    return r[0] if r else None


def test_happy_path_saves_token_enables_channel_and_prints_code(svc, fake):
    rc, sc = go(svc, fake, ["1"], [fake.token])
    assert rc == 0
    tok = svc.cfg.home / "telegram_token"
    assert tok.read_text().strip() == fake.token
    assert stat.S_IMODE(tok.stat().st_mode) == 0o600
    assert enabled(svc)
    code = code_of(svc)
    assert code and code in sc.text and "@pith_test_bot" in sc.text and "pith run" in sc.text
    assert fake.token not in sc.text  # the token is never echoed


def test_bad_token_then_good_token(svc, fake):
    rc, sc = go(svc, fake, ["1"], ["999:wrong", fake.token])
    assert rc == 0 and "rejected" in sc.text
    assert (svc.cfg.home / "telegram_token").read_text().strip() == fake.token


def test_three_bad_tokens_give_up_and_write_nothing(svc, fake):
    rc, _ = go(svc, fake, ["1"], ["1:a", "2:b", "3:c"])
    assert rc == 1
    assert not (svc.cfg.home / "telegram_token").exists() and not enabled(svc)


def test_unreachable_telegram_saves_anyway(svc, fake):
    rc, sc = go(svc, fake, ["1"], ["123:offline-token"], api_base="http://127.0.0.1:9")
    assert rc == 0 and "could not reach" in sc.text.lower()
    assert (svc.cfg.home / "telegram_token").read_text().strip() == "123:offline-token"
    assert enabled(svc)


def test_skip_writes_nothing(svc, fake):
    rc, _ = go(svc, fake, ["0"], [])
    assert rc == 0 and not (svc.cfg.home / "telegram_token").exists() and not enabled(svc)


def test_existing_config_is_kept_and_backed_up(svc, fake):
    cfgfile = svc.cfg.home / "config.toml"
    cfgfile.write_text("[http]\nport = 9999\n")
    rc, _ = go(svc, fake, ["1"], [fake.token])
    assert rc == 0
    new = load_config(cfgfile, {"PITH_HOME": str(svc.cfg.home)})
    assert new.http_port == 9999 and new.channels["telegram"]["enabled"] is True
    assert cfgfile.with_name("config.toml.bak").read_text() == "[http]\nport = 9999\n"


def test_existing_token_can_be_kept(svc, fake):
    (svc.cfg.home / "telegram_token").write_text("111:old-token\n")
    rc, sc = go(svc, fake, ["1", "n"], [])  # "n": do not replace; no token prompt happens
    assert rc == 0
    assert (svc.cfg.home / "telegram_token").read_text().strip() == "111:old-token"
    assert enabled(svc) and code_of(svc) in sc.text


def test_cli_setup_skip_and_plain_init_still_non_interactive(tmp_path):
    home = tmp_path / "h"
    env = {**os.environ, "PITH_HOME": str(home), "HOME": str(home) + "-userhome"}

    def run(*args, stdin=""):
        return subprocess.run([sys.executable, "-m", "pith.cli", *args], env=env, input=stdin,
                              capture_output=True, text=True, timeout=60, check=False)
    r = run("init")  # no terminal: no prompts, same output as before
    assert r.returncode == 0 and "initialized" in r.stdout and "Select" not in r.stdout
    r = run("setup", stdin="0\n")
    assert r.returncode == 0 and "Select" in r.stdout
