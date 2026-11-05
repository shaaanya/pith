"""Telegram Desktop export importer (`result.json`).

UNVERIFIED against a real export: written from the documented format (top-level `id`,
`messages[]` with `id`, `type`, `date`, `text` as str or list of str/entity dicts,
`text_entities`, `forwarded_from`, `photo`/`file` paths relative to the export dir). Test fixture
is hand-built from that description.

One message = one submission (a URL-only message becomes a URL submission). External id
`<chat id>:<message id>` makes re-import a no-op. Service messages are skipped. Missing/escaping
media paths become a note, not a crash.
The whole JSON is loaded in memory (ponytail: use a streaming parser for multi-GB exports).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

NAME = "telegram_export"
_URL = re.compile(r"https?://\S+")


@dataclass
class ImportReport:
    """Counts of what an import did."""
    submitted: int = 0
    duplicates: int = 0
    skipped: int = 0


def flatten_text(text) -> str:
    """Telegram `text` (a string or a list of strings/entity dicts) as plain text."""
    if isinstance(text, str):
        return text
    if isinstance(text, list):
        return "".join(t if isinstance(t, str) else str(t.get("text", "")) for t in text)
    return ""


def _urls(msg: dict) -> list[str]:
    out = []
    for e in msg.get("text_entities") or (msg["text"] if isinstance(msg.get("text"), list) else []):
        if not isinstance(e, dict):
            continue
        kind = e.get("type")
        u = e.get("href") if kind == "text_link" else e.get("text") if kind == "link" else None
        if isinstance(u, str) and _URL.fullmatch(u.strip()) and u.strip() not in out:
            out.append(u.strip())
    return out


def _load(export_json: Path) -> dict:
    try:
        data = json.loads(export_json.read_text("utf-8"))
    except (OSError, ValueError) as e:  # missing, unreadable, empty, truncated, not UTF-8
        raise ValueError(f"not a Telegram export: {export_json}: {e}") from e
    if not isinstance(data, dict) or not isinstance(data.get("messages"), list):
        raise ValueError(f"not a Telegram export: {export_json}: "
                         "expected an object with a messages list")
    return data


def _resolve_media(media, root: Path, text: str) -> tuple[Path | None, str]:
    """-> (existing file inside the export dir or None, text with a note when it is missing)."""
    if isinstance(media, str):
        cand = (root / media).resolve()
        if cand.is_relative_to(root) and cand.is_file():
            return cand, text
        return None, (text + f"\n[missing media: {media}]").strip()
    if media is not None:
        return None, (text + "\n[missing media]").strip()
    return None, text


def _content(m: dict, root: Path, since: str | None):
    """-> (text, file path or None, context lines) for a message, or None to skip it."""
    if not isinstance(m, dict) or m.get("type") != "message" or "id" not in m:
        return None
    date = str(m.get("date", ""))
    if since and date < since:
        return None
    text = flatten_text(m.get("text")).strip()
    urls = _urls(m)
    fwd = m.get("forwarded_from")
    ctx = [f"Telegram message {date}" + (f" from {m['from']}" if m.get("from") else "")]
    if fwd:
        ctx.append(f"forwarded from {fwd}")
    media = m.get("photo") or m.get("file")
    path, text = _resolve_media(media, root, text)
    if media is not None and path is None and not flatten_text(m.get("text")).strip() and not urls:
        return None  # nothing but media we cannot find
    for u in urls:  # text_link hrefs not visible in the text
        if u not in text:
            text += f"\n{u}"
    if not text and path is None:
        return None
    return text, path, ctx


def import_export(inbox, export_json: Path, *, since: str | None = None) -> ImportReport:
    """Submit every message of a Telegram Desktop export; re-importing is a no-op."""
    export_json = Path(export_json)
    data = _load(export_json)
    root = export_json.parent.resolve()
    chat = data.get("id", data.get("name", "chat"))
    rep = ImportReport()
    for m in data["messages"]:
        content = _content(m, root, since)
        if content is None:
            rep.skipped += 1
            continue
        text, path, ctx = content
        kw = {"adapter": NAME, "external_id": f"{chat}:{m['id']}"}
        if path:
            if text:
                ctx.append(text)
            r = inbox.submit(file=path, filename=path.name, user_context="\n".join(ctx), **kw)
        else:
            r = inbox.submit(text=text.strip(), user_context="\n".join(ctx), **kw)
        if r.duplicate_of:
            rep.duplicates += 1
        else:
            rep.submitted += 1
    return rep
