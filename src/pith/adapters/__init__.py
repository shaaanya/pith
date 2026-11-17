"""Channels: one-way feeders that put items into the inbox. Core never imports this package;
channels only call Inbox.submit.

A channel is built by a factory `(svc, section) -> Channel` registered in CHANNELS, where `section`
is its `[channels.<name>]` config table. See `adapters/base.py` for the protocol."""
from __future__ import annotations

from typing import TYPE_CHECKING

from pith.adapters.base import Channel

if TYPE_CHECKING:  # pragma: no cover
    from pith.config import Config
    from pith.services import Services


def _fs(svc: Services, section: dict) -> Channel:
    from pith.adapters.fs import FsAdapter
    return FsAdapter(svc.inbox, svc.cfg.watch_dirs, interval=float(section.get("interval", 5.0)))


def _telegram(svc: Services, section: dict) -> Channel:
    from pith.adapters.telegram_bot import TelegramChannel
    return TelegramChannel(svc, section)  # token is read on the first poll


CHANNELS = {"fs": _fs, "telegram": _telegram}


def enabled_channels(cfg: Config) -> list[str]:
    """fs unless `[channels.fs] enabled = false`; any other channel only when `enabled = true`."""
    names = [] if cfg.channels.get("fs", {}).get("enabled") is False else ["fs"]
    return names + [n for n, sec in cfg.channels.items() if n != "fs" and sec.get("enabled") is True]


def build_channel(name: str, svc: Services) -> Channel:
    """The channel `name` built from its config section; ValueError if there is no such channel."""
    if name not in CHANNELS:
        raise ValueError(f"unknown channel {name!r} (known: {', '.join(sorted(CHANNELS))})")
    return CHANNELS[name](svc, svc.cfg.channels.get(name, {}))
