"""Receive-only Telegram bot channel: the user shares links, notes and files to a bot they own.

Outbound only: long-polls `getUpdates` (no webhook, no open port). It sends exactly three short
messages, all in the pairing handshake and only to an unpaired chat while a pairing code is active
(`pith setup` started one): "Input the one-time code:", a "doesn't match" hint, and the
confirmation. It never replies to content. Only allowlisted chats are accepted; every other
message is ignored silently. One update is confirmed (stored `offset` advanced) only after it was fully handled, and
`external_id = "<chat_id>:<message_id>"` makes a redelivery a no-op, so a crash never loses or
duplicates an item.

Mapping: a bare URL is a URL item; text with URLs is one item per URL with the text as context;
other text is a note; document/photo/voice/audio/video/video_note is downloaded (capped by
cfg.max_fetch_bytes) and submitted as a file with the caption as context. The bot token is read
from PITH_TELEGRAM_TOKEN or <home>/telegram_token and never appears in a raised message.
"""
from __future__ import annotations

import hmac
import json
import logging
import os
import re
import secrets
import urllib.error
import urllib.request
from collections.abc import Mapping
from pathlib import Path

from pith.adapters.base import ChannelState

NAME = "telegram"
DEFAULT_API = "https://api.telegram.org"
_TOKEN = re.compile(r"\d+:[A-Za-z0-9_-]+")
log = logging.getLogger(__name__)
_URL = re.compile(r"https?://\S+")
_TRAIL = ".,;:!?)]}>\"'"
_MEDIA = ("document", "photo", "voice", "audio", "video", "video_note")
_DEFAULT_NAME = {"document": "document", "photo": "photo.jpg", "voice": "voice.ogg",
                 "audio": "audio.mp3", "video": "video.mp4", "video_note": "video.mp4"}
_DEFAULT_MIME = {"photo": "image/jpeg", "voice": "audio/ogg", "video_note": "video/mp4"}
MSG_ASK = "Input the one-time code:"
MSG_WRONG = "That code doesn't match. Try again:"
MSG_DONE = "You're all set! Now just send me something and I'll get the Pith of it \U0001F642"


def check_token(token: str, api_base: str = DEFAULT_API) -> str:
    """The bot's @username when Telegram accepts the token (one `getMe` call).

    ValueError: the token is malformed or rejected. RuntimeError: Telegram was not reachable.
    Neither message contains the token."""
    if not _TOKEN.fullmatch(token):
        raise ValueError("this does not look like a bot token (expected 123456:ABC-...)")
    req = urllib.request.Request(f"{api_base.rstrip('/')}/bot{token}/getMe", data=b"{}",
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code in (401, 404):
            raise ValueError("Telegram rejected this token") from None
        raise RuntimeError(f"HTTP {e.code}") from None
    except (OSError, ValueError) as e:
        raise RuntimeError(type(e).__name__) from None
    name = ((data or {}).get("result") or {}).get("username") if isinstance(data, dict) else None
    return f"@{name}" if name else "your bot"


def save_token(cfg, token: str) -> Path:
    """Write the token to <home>/telegram_token with mode 0600 (atomically)."""
    home = Path(cfg.home)
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    path, tmp = home / "telegram_token", home / f".telegram_token.tmp{os.getpid()}"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(token + "\n")
    os.replace(tmp, path)
    return path


class Refused(RuntimeError):
    """Telegram refused one request for good (bad file id, file too big): skip, do not retry."""


def load_token(cfg, env: Mapping = os.environ) -> str:
    """The bot token: PITH_TELEGRAM_TOKEN, else <home>/telegram_token; ValueError if neither."""
    token = (env.get("PITH_TELEGRAM_TOKEN") or "").strip()
    if not token:
        try:
            token = (Path(cfg.home) / "telegram_token").read_text("utf-8").strip()
        except OSError:
            token = ""
    if not token:
        raise ValueError("no Telegram bot token: set PITH_TELEGRAM_TOKEN or put it in "
                         f"{Path(cfg.home) / 'telegram_token'}")
    return token


def new_pairing_code(state: ChannelState) -> str:
    """Store and return a fresh one-time code; sending it to the bot pairs that chat.

    ponytail: no expiry, and a new code replaces the old one; add a TTL if codes get shared."""
    code = secrets.token_urlsafe(9)
    state.set("pairing_code", code)
    return code


class TelegramChannel:
    """Polls one bot's updates and submits what allowlisted chats send."""

    name = NAME
    interval = 1.0

    def __init__(self, svc, section: dict, token: str | None = None):
        """Builds nothing that can fail: the token and the config values are read on the first
        poll(), so a missing token or a bad value is a recorded `last_error` that fixes itself
        once corrected, never a dead `pith run`."""
        self.svc, self.inbox, self.token, self.section = svc, svc.inbox, token, section
        self.state = ChannelState(svc.conn, NAME)
        self._ready = False
        self.base, self.poll_timeout, self.allowed = "", 25, set()

    def _setup(self) -> None:
        sec = self.section
        token = self.token or load_token(self.svc.cfg)
        self.base = str(sec.get("api_base", "https://api.telegram.org")).rstrip("/")
        self.poll_timeout = int(sec.get("poll_timeout", 25))
        self.allowed = {int(c) for c in sec.get("allowed_chat_ids", [])}
        self.token, self._ready = token, True

    # -- transport -------------------------------------------------------------------------

    def _clean(self, text) -> str:
        return str(text).replace(self.token, "***")[:200]

    def _post(self, method: str, payload: dict):
        req = urllib.request.Request(
            f"{self.base}/bot{self.token}/{method}", data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.poll_timeout + 10) as r:
                data = json.loads(r.read())
        except urllib.error.HTTPError as e:
            # `from None`: the chained error carries the URL, and the URL carries the token
            cls = Refused if e.code in (400, 404) else RuntimeError
            raise cls(f"telegram {method}: HTTP {e.code}") from None
        except (OSError, ValueError) as e:  # URLError is an OSError
            raise RuntimeError(f"telegram {method}: {type(e).__name__}") from None
        if not isinstance(data, dict) or not data.get("ok"):
            raise Refused(f"telegram {method}: {self._clean((data or {}).get('description', 'error'))}")
        return data["result"]

    def _download(self, file_id: str, limit: int) -> bytes | None:
        """The file's bytes, or None when it is larger than `limit`."""
        path = self._post("getFile", {"file_id": file_id}).get("file_path")
        if not path:
            return None
        try:
            with urllib.request.urlopen(f"{self.base}/file/bot{self.token}/{path}",
                                        timeout=60) as r:
                data = r.read(limit + 1)
        except urllib.error.HTTPError as e:
            # a 4xx will not get better on retry: skip the file, do not wedge the channel
            cls = Refused if 400 <= e.code < 500 and e.code not in (401, 429) else RuntimeError
            raise cls(f"telegram download: HTTP {e.code}") from None
        except OSError as e:
            raise RuntimeError(f"telegram download: {type(e).__name__}") from None
        return None if len(data) > limit else data

    # -- channel ---------------------------------------------------------------------------

    def _allowed(self) -> set[int]:
        """Chats from config plus chats paired by sending the one-time code."""
        return self.allowed | set(json.loads(self.state.get("paired") or "[]"))

    def _say(self, chat: int, text: str) -> None:
        """A handshake message. A failed send is logged, never fatal: pairing is already saved."""
        try:
            self._post("sendMessage", {"chat_id": chat, "text": text})
        except RuntimeError as e:
            log.warning("telegram: could not send a setup message: %s", e)

    def _handshake(self, chat, msg: dict) -> None:
        """Pairing, for a chat that is not allowed yet. Silent unless a code is active (the owner
        started `pith setup`), so strangers who find the bot get no reaction at all."""
        code, text = self.state.get("pairing_code"), msg.get("text")
        if not code or not isinstance(chat, int) or not isinstance(text, str) or not text.strip():
            return
        text = text.strip()
        if text.startswith("/start"):
            self._say(chat, MSG_ASK)
        elif hmac.compare_digest(text.encode(), code.encode()):
            paired = {*json.loads(self.state.get("paired") or "[]"), chat}
            self.state.set("paired", json.dumps(sorted(paired)))
            self.state.set("pairing_code", "")  # single use
            self._say(chat, MSG_DONE)
        else:
            self._say(chat, MSG_WRONG)

    def poll(self) -> int:
        """One getUpdates round; returns the number of items submitted."""
        if not self._ready:
            self._setup()
        body = {"timeout": self.poll_timeout, "allowed_updates": ["message"]}
        if (off := self.state.get("offset")) is not None:
            body["offset"] = int(off)
        n = 0
        for u in self._post("getUpdates", body):
            n += self._handle(u.get("message"))
            self.state.set("offset", str(u["update_id"] + 1))
        return n

    def _handle(self, msg) -> int:
        if not isinstance(msg, dict):
            return 0
        chat = (msg.get("chat") or {}).get("id")
        if chat not in self._allowed():
            self._handshake(chat, msg)
            return 0
        if str(msg.get("text") or "").strip().startswith("/start"):
            return 0  # Telegram's Start button, not something to save
        ext = f"{chat}:{msg.get('message_id')}"
        for kind in _MEDIA:
            if kind in msg:
                return self._file(msg, kind, ext)
        text = msg.get("text")
        if not isinstance(text, str) or not text.strip():
            return 0
        urls = self._urls(msg, text)
        if not urls and self._note_on_reply(msg, chat, text):
            return 1
        if len(urls) == 1 and text.strip() == urls[0]:
            self.inbox.submit(adapter=NAME, text=urls[0], external_id=ext)
            return 1
        for i, url in enumerate(urls):
            self.inbox.submit(adapter=NAME, text=url, user_context=text,
                              external_id=f"{ext}:{i}")
        if urls:
            return len(urls)
        self.inbox.submit(adapter=NAME, text=text, external_id=ext)
        return 1

    def _note_on_reply(self, msg: dict, chat, text: str) -> bool:
        """A plain-text reply to a message already saved adds your words to that item (what to
        keep, why) instead of becoming a new item. False when it replies to nothing we saved."""
        mid = (msg.get("reply_to_message") or {}).get("message_id")
        if mid is None:
            return False
        for ext in (f"{chat}:{mid}", f"{chat}:{mid}:0"):
            if iid := self.inbox.find_by_external(NAME, ext):
                self.inbox.add_note(iid, text)
                self.inbox.retry(iid)
                return True
        return False

    @staticmethod
    def _urls(msg: dict, text: str) -> list[str]:
        found = [m.group().rstrip(_TRAIL) for m in _URL.finditer(text)]
        found += [e["url"] for e in msg.get("entities") or []
                  if isinstance(e, dict) and e.get("type") == "text_link"
                  and isinstance(e.get("url"), str) and _URL.fullmatch(e["url"])]
        return list(dict.fromkeys(u for u in found if _URL.fullmatch(u)))

    def _file(self, msg: dict, kind: str, ext: str) -> int:
        obj = msg[kind]
        if kind == "photo":  # a list of sizes; take the largest
            obj = max((p for p in obj if isinstance(p, dict)), default=None,
                      key=lambda p: (p.get("width", 0) * p.get("height", 0), p.get("file_size", 0))
                      ) if isinstance(obj, list) else None
        if not isinstance(obj, dict) or not obj.get("file_id"):
            return 0
        limit = self.svc.cfg.max_fetch_bytes
        size = obj.get("file_size")
        if isinstance(size, int) and size > limit:
            log.warning("telegram: skipping %s: file larger than max_fetch_bytes", ext)
            return 0
        try:
            data = self._download(obj["file_id"], limit)
        except Refused as e:  # e.g. Telegram's own 20 MB getFile limit: never going to work
            log.warning("telegram: skipping %s: %s", ext, e)
            return 0
        if data is None:
            log.warning("telegram: skipping %s: file larger than max_fetch_bytes", ext)
            return 0
        self.inbox.submit(
            adapter=NAME, file=data, filename=obj.get("file_name") or _DEFAULT_NAME[kind],
            mime=obj.get("mime_type") or _DEFAULT_MIME.get(kind),
            user_context=msg.get("caption") or None, external_id=ext)
        return 1
