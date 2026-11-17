"""Channel protocol: a one-way feeder that puts items into the inbox queue.

A channel is a name, an interval and `poll()` (one pass: fetch what is new, `Inbox.submit()` it,
return how many were submitted). `run_channel` owns the loop, the stop flag, error backoff and the
status that the CLI and dashboard read from `channel_state`. Channels only receive; the one
exception is the Telegram pairing handshake (see telegram_bot.py).
"""
from __future__ import annotations

import logging
import sqlite3
import threading
from typing import Protocol

from pith.ids import utcnow

log = logging.getLogger(__name__)


class Channel(Protocol):  # pylint: disable=too-few-public-methods  # the protocol is the point
    """What every channel provides."""

    name: str
    interval: float

    def poll(self) -> int:
        """One pass; submits through Inbox.submit() and returns the number submitted."""


class ChannelState:
    """Small per-channel key/value store (cursors, status) in the `channel_state` table."""

    def __init__(self, conn: sqlite3.Connection, channel: str):
        self.conn, self.channel = conn, channel

    def get(self, key: str, default: str | None = None) -> str | None:
        """The stored value, or `default`."""
        row = self.conn.execute("SELECT value FROM channel_state WHERE channel=? AND key=?",
                                (self.channel, key)).fetchone()
        return row[0] if row else default

    def set(self, key: str, value: str) -> None:
        """Store `value` (upsert)."""
        self.conn.execute(
            "INSERT INTO channel_state(channel, key, value) VALUES (?,?,?)"
            " ON CONFLICT(channel, key) DO UPDATE SET value=excluded.value",
            (self.channel, key, value))


def run_channel(channel: Channel, state: ChannelState, stop: threading.Event, *,
                max_backoff: float = 60.0) -> None:
    """Poll until `stop`. An error is recorded in `last_error` and retried with doubling backoff
    (capped at `max_backoff`); a success clears it and records `last_ok_at` and `submitted`."""
    delay = channel.interval
    while not stop.is_set():
        try:
            n = channel.poll()
        except Exception as e:  # noqa: BLE001  # pylint: disable=broad-exception-caught
            # a channel must survive network errors; the message is shown to the user, so it must
            # not carry secrets (each channel is responsible for that in what it raises)
            state.set("last_error", f"{type(e).__name__}: {e}"[:500])
            log.warning("channel %s: %s", channel.name, state.get("last_error"))
            stop.wait(delay)
            delay = min(max(delay, 0.001) * 2, max_backoff)
            continue
        delay = channel.interval
        state.set("last_ok_at", utcnow())
        state.set("last_error", "")
        if n:
            state.set("submitted", str(int(state.get("submitted", "0")) + n))
        elif state.get("submitted") is None:
            state.set("submitted", "0")
        stop.wait(channel.interval)
