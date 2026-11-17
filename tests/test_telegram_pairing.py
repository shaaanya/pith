"""Pairing: a chat becomes allowed by sending the one-time code; the bot never replies."""
import json
import os
import subprocess
import sys

import pytest
from stubs.fake_telegram import FakeTelegram

from pith.adapters.telegram_bot import (MSG_ASK, MSG_DONE, MSG_WRONG, TelegramChannel,
                                        new_pairing_code)
from pith.store.db import connect


@pytest.fixture(name="fake")
def fake_fixture():
    with FakeTelegram() as f:
        yield f


def channel(svc, fake, allowed=()):
    return TelegramChannel(svc, {"api_base": fake.url, "poll_timeout": 0,
                                 "allowed_chat_ids": list(allowed)}, fake.token)


def n_items(svc):
    return svc.conn.execute("SELECT COUNT(*) FROM inbox_items").fetchone()[0]


def test_pairing_code_adds_chat_confirms_once_and_is_single_use(svc, fake):
    ch = channel(svc, fake)
    code = new_pairing_code(ch.state)
    fake.message(999, code)
    fake.message(1000, code)  # the same code again, from another chat: the code is used up
    assert ch.poll() == 0
    assert json.loads(ch.state.get("paired")) == [999]
    assert n_items(svc) == 0
    assert fake.sent() == [(999, MSG_DONE)]  # the only message the bot ever sent


def test_start_while_a_code_is_active_asks_for_it(svc, fake):
    ch = channel(svc, fake)
    new_pairing_code(ch.state)
    fake.message(999, "/start")
    ch.poll()
    assert fake.sent() == [(999, MSG_ASK)] and ch.state.get("paired") is None


def test_start_without_a_pairing_in_progress_stays_silent(svc, fake):
    ch = channel(svc, fake)
    fake.message(999, "/start")
    fake.message(999, "hello?")
    ch.poll()
    assert fake.sent() == []  # strangers get no reaction unless the owner started a setup


def test_wrong_code_gets_a_retry_hint_and_does_not_pair(svc, fake):
    ch = channel(svc, fake)
    code = new_pairing_code(ch.state)
    fake.message(999, "not-the-code")
    ch.poll()
    assert fake.sent() == [(999, MSG_WRONG)]
    assert ch.state.get("paired") is None and ch.state.get("pairing_code") == code


def test_paired_chat_gets_no_replies_and_start_is_not_a_note(svc, fake):
    ch = channel(svc, fake, allowed=[999])
    fake.message(999, "/start")
    fake.message(999, "https://example.com/a")
    fake.message(999, "a plain note")
    assert ch.poll() == 2
    assert fake.sent() == []


def test_failing_confirmation_does_not_break_pairing(svc, fake):
    ch = channel(svc, fake)
    fake.fail_sends = True
    fake.message(999, new_pairing_code(ch.state))
    assert ch.poll() == 0  # no exception
    assert json.loads(ch.state.get("paired")) == [999]


def test_paired_chat_messages_are_then_accepted(svc, fake):
    ch = channel(svc, fake)
    fake.message(999, new_pairing_code(ch.state))
    ch.poll()
    fake.message(999, "a note from my phone")
    assert ch.poll() == 1
    fake.message(999, "another one")
    assert channel(svc, fake).poll() == 1  # persisted: a fresh channel object still accepts it
    assert n_items(svc) == 2


def test_empty_message_never_pairs_after_the_code_was_used(svc, fake):
    ch = channel(svc, fake)
    fake.message(999, new_pairing_code(ch.state))
    ch.poll()
    fake.message(5, "")  # the cleared code is "": an empty text must not equal it
    ch.poll()
    assert json.loads(ch.state.get("paired")) == [999]


def test_cli_adapters_pair_prints_a_stored_code(tmp_path):
    home = tmp_path / "h"
    env = {**os.environ, "PITH_HOME": str(home), "HOME": str(home) + "-userhome"}

    def run(*args):
        return subprocess.run([sys.executable, "-m", "pith.cli", *args], env=env,
                              capture_output=True, text=True, timeout=60, check=False)
    assert run("init").returncode == 0
    r = run("adapters", "pair", "telegram")
    assert r.returncode == 0, r.stderr
    conn = connect(home / "infoparser.db")
    code = conn.execute("SELECT value FROM channel_state WHERE channel='telegram'"
                        " AND key='pairing_code'").fetchone()[0]
    assert code and code in r.stdout
    assert "[channels.telegram]\nenabled = true" in r.stdout  # pasteable, valid TOML
