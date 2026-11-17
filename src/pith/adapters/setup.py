"""`pith setup` (and the tail of `pith init` in a terminal): set up a capture channel step by step.

Telegram: ask for the bot token (hidden), check it with Telegram, save it to <home>/telegram_token
(mode 0600), enable `[channels.telegram]` in the config file, and print a one-time pairing code to
send to the bot. All prompts go through injected functions so the flow is testable; it prints the
bot's @username but never the token.
"""
from __future__ import annotations

import getpass
import sys

from pith import settings
from pith.adapters.base import ChannelState
from pith.adapters.telegram_bot import (DEFAULT_API, check_token, load_token, new_pairing_code,
                                        save_token)

MAX_TRIES = 3


def _secret(prompt: str = "") -> str:
    """Hidden input in a terminal; plain input when stdin is piped."""
    return getpass.getpass(prompt) if sys.stdin.isatty() else input(prompt)


def run_setup(svc, *, input_fn=input, secret_fn=_secret, out=print,
              api_base: str = DEFAULT_API) -> int:
    """Interactive channel setup; returns a process exit code (0 done or skipped, 1 failed)."""
    out("Select the channel you want to set up:")
    out("  1) Telegram bot  (send links, notes and files to Pith from your phone)")
    out("  0) Skip")
    choice = input_fn("> ").strip().lower()
    if choice in ("", "0", "q", "skip"):
        out("Skipped. Run `pith setup` any time to set up a channel.")
        return 0
    if choice not in ("1", "telegram"):
        out(f"Unknown choice {choice!r}; nothing changed.")
        return 1
    return _telegram(svc, input_fn, secret_fn, out, api_base)


def _ask_token(secret_fn, out, api_base: str) -> tuple[str, str | None] | None:
    """(token, @username or None when Telegram was unreachable), or None after too many bad tries."""
    for _ in range(MAX_TRIES):
        token = secret_fn("Paste the bot token from @BotFather (input is hidden): ").strip()
        try:
            return token, check_token(token, api_base)
        except ValueError as e:
            out(f"That token was rejected: {e}. Try again.")
        except RuntimeError:
            out("Could not reach Telegram to check the token, so it is saved unchecked.")
            return token, None
    out(f"Giving up after {MAX_TRIES} attempts. Nothing was changed.")
    return None


def _telegram(svc, input_fn, secret_fn, out, api_base: str) -> int:
    cfg = svc.cfg
    name = None
    keep = False
    try:
        existing = load_token(cfg, env={})
    except ValueError:
        existing = None
    if existing:
        keep = input_fn("A bot token is already saved. Replace it? [y/N] ").strip().lower() != "y"
    if keep:
        try:
            name = check_token(existing, api_base)
        except (ValueError, RuntimeError):
            name = None
    else:
        got = _ask_token(secret_fn, out, api_base)
        if got is None:
            return 1
        token, name = got
        try:
            path = save_token(cfg, token)
        except OSError as e:
            out(f"error: cannot save the token: {e}")
            return 1
        out(f"Saved the token to {path} (readable only by you).")
    try:
        settings.enable_channel(cfg, "telegram")
    except ValueError as e:
        out(f"error: {e}")
        return 1
    out("Telegram channel enabled in the config file.")
    code = new_pairing_code(ChannelState(svc.conn, "telegram"))
    bot = name or "your bot"
    out("")
    out("Start Pith with:  pith run")
    out(f"Then open a private chat with {bot} on your phone, press Start, and when the bot asks,")
    out("send it this one-time code:")
    out(f"    {code}")
    out("The bot confirms; after that, share links, notes and files to it from anywhere.")
    out("You're all set!")
    return 0
