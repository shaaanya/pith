"""Shared by the HTTP ingest adapter and the dashboard: submit-body validation, multipart
parsing, local token."""
from __future__ import annotations

import os
import re
import secrets
import time
from email.parser import BytesParser
from email.policy import HTTP
from pathlib import Path

from infoparser.inbox.service import Inbox

NAME = "http"
_HTTP_URL = re.compile(r"https?://\S+")
LOOPBACK = {"127.0.0.1", "::1", "localhost"}


def safe_filename(name: str | None) -> str | None:
    """Basename of an uploaded filename without control chars or leading dots (<=200), or None."""
    name = re.sub(r"[\x00-\x1f\x7f]", "", (name or "").replace("\\", "/"))
    name = name.split("/")[-1].strip().lstrip(".")
    return name[:200] or None


def handle(inbox: Inbox, body: dict, adapter: str = NAME) -> dict:
    """Validate and submit. ValueError -> caller answers 400."""
    if not isinstance(body, dict):
        raise ValueError("body must be a JSON object")
    url, text, ctx, plat, file = (
        body.get(k) for k in ("url", "text", "context", "platform", "file"))
    for k, v in (("url", url), ("text", text), ("context", ctx), ("platform", plat)):
        if v is not None and not isinstance(v, str):
            raise ValueError(f"{k} must be a string")
    if sum(bool(x) for x in (url, text, file)) != 1:
        raise ValueError("exactly one of url, text or file is required")
    if url and not _HTTP_URL.fullmatch(url.strip()):
        raise ValueError("url must be http(s)")
    kw = {"adapter": adapter, "user_context": ctx or None, "platform": plat or None}
    if file:
        r = inbox.submit(file=bytes(file), filename=safe_filename(body.get("filename")), **kw)
    else:
        r = inbox.submit(text=(url or text).strip(), **kw)
    status = inbox.get(r.id)["status"]
    return {"id": r.id, "status": status, "duplicate": r.duplicate_of is not None}


def load_token(cfg) -> str:
    """The configured token, else the one in `<home>/http_token` (created 0600 on first use)."""
    if cfg.http_token:
        return cfg.http_token
    p = Path(cfg.home) / "http_token"
    Path(cfg.home).mkdir(parents=True, exist_ok=True)
    for _ in range(50):
        try:  # O_EXCL: exactly one creator wins; everyone else re-reads the winner's token
            fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            tok = p.read_text().strip()
            if tok:
                if p.stat().st_mode & 0o077:
                    p.chmod(0o600)
                return tok
            if _ >= 5:  # empty for 100ms: a leftover, not a creator mid-write; fill it in place
                tok = secrets.token_urlsafe(32)
                with open(p, "w", encoding="utf-8") as f:
                    f.write(tok + "\n")
                p.chmod(0o600)
                return tok
            time.sleep(0.02)  # creator may not have written yet
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(secrets.token_urlsafe(32) + "\n")
    raise RuntimeError(f"cannot obtain a token from {p} (empty file?)")


def parse_multipart(ctype: str, raw: bytes) -> dict:
    """Parse a multipart/form-data body into {field: text}, with `file`/`filename` for an upload."""
    head = b"Content-Type: " + ctype.encode() + b"\r\n\r\n"
    msg = BytesParser(policy=HTTP).parsebytes(head + raw)
    out: dict = {}
    for part in msg.iter_parts() if msg.is_multipart() else []:
        name = part.get_param("name", header="content-disposition")
        if not name:
            continue
        if part.get_filename() is not None:
            out["file"], out["filename"] = part.get_payload(decode=True) or b"", part.get_filename()
        else:
            out[name] = part.get_content()
    return out
