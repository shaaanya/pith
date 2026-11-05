from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

from infoparser.config import Config
from infoparser.domain.models import Status, SubmitResult
from infoparser.domain.urls import canonicalize_url, detect_platform
from infoparser.ids import new_id, utcnow
from infoparser.store.blobs import BlobStore
from infoparser.store.db import transaction

_BARE_URL = re.compile(r"https?://\S+")
_DEAD = (Status.FAILED, Status.NEEDS_CLARIFICATION)


class Inbox:
    def __init__(self, conn: sqlite3.Connection, blobs: BlobStore, cfg: Config):
        self.conn, self.blobs, self.cfg = conn, blobs, cfg

    def _tx(self):
        return transaction(self.conn)

    def submit(
        self,
        *,
        adapter: str,
        text: str | None = None,
        file: Path | bytes | None = None,
        filename: str | None = None,
        mime: str | None = None,
        user_context: str | None = None,
        platform: str | None = None,
        external_id: str | None = None,
    ) -> SubmitResult:
        """external_id: adapter-scoped stable id (e.g. Telegram chat:message). A repeat with the same
        (adapter, external_id) is a pure no-op duplicate: no new row, no context appended, no requeue."""
        if (text is None) == (file is None):
            raise ValueError("exactly one of text or file is required")
        sha = url = None
        if file is not None:
            kind = "file"
            # blob first: content-addressed and idempotent, so an orphan after rollback is harmless
            sha = self.blobs.put_bytes(file) if isinstance(file, bytes) else self.blobs.put_file(file)
        elif _BARE_URL.fullmatch(text.strip()):
            kind, url = "url", canonicalize_url(text)
        else:
            kind = "text"
        now = utcnow()
        with self._tx():
            if external_id:
                seen = self.conn.execute("SELECT inbox_id AS id FROM external_ids WHERE adapter=? AND external_id=?",
                                         (adapter, external_id)).fetchone()
                if seen:
                    return SubmitResult(seen["id"], seen["id"], False)
            if url:
                q, key = "canonical_url=?", url
            elif sha:
                q, key = "blob_sha256=?", sha
            else:
                q = key = None
            old = q and self.conn.execute(
                f"SELECT * FROM inbox_items WHERE {q} AND duplicate_of IS NULL "
                "ORDER BY submitted_at LIMIT 1", (key,)
            ).fetchone()
            if old:
                requeue = old["status"] in _DEAD
                self._append_context(old["id"], user_context, now)
                self.conn.execute(
                    "INSERT INTO provenance_log(source_id, inbox_id, url, added_at) VALUES (?,?,?,?)",
                    (old["source_id"], old["id"], url, now),
                )
                if requeue:
                    self._requeue(old["id"], now)
                self._record_external(adapter, external_id, old["id"])
                return SubmitResult(old["id"], old["id"], requeue)
            iid = new_id()
            self.conn.execute(
                "INSERT INTO inbox_items(id, adapter, platform, submitted_at, kind_hint, payload_text,"
                " blob_sha256, original_filename, mime, canonical_url, user_context, status, updated_at, external_id)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (iid, adapter, platform or detect_platform(url), now, kind, text, sha, filename,
                 mime, url, user_context or None, Status.PENDING, now, external_id),
            )
            self._insert_job(iid)
            self._record_external(adapter, external_id, iid)
        return SubmitResult(iid)

    def _record_external(self, adapter, external_id, iid) -> None:
        if external_id:
            self.conn.execute("INSERT OR IGNORE INTO external_ids(adapter, external_id, inbox_id) VALUES (?,?,?)",
                              (adapter, external_id, iid))

    def _append_context(self, iid: str, ctx: str | None, now: str) -> None:
        cur = self.conn.execute("SELECT user_context FROM inbox_items WHERE id=?", (iid,)).fetchone()
        have = "\n\n" + (cur["user_context"] or "") + "\n\n"  # block-wise match; ctx may itself hold blank lines
        if ctx and "\n\n" + ctx + "\n\n" not in have:
            self.conn.execute(
                "UPDATE inbox_items SET user_context = CASE WHEN user_context IS NULL OR user_context=''"
                " THEN ? ELSE user_context || char(10,10) || ? END, updated_at=? WHERE id=?",
                (ctx, ctx, now, iid),
            )

    def _insert_job(self, iid: str) -> None:
        self.conn.execute("INSERT INTO jobs(id, inbox_id) VALUES (?,?)", (new_id(), iid))

    def _requeue(self, iid: str, now: str) -> None:
        self.conn.execute(
            "UPDATE inbox_items SET status=?, error=NULL, attempts=0, updated_at=? WHERE id=?",
            (Status.PENDING, now, iid),
        )
        live = self.conn.execute(
            "SELECT 1 FROM jobs WHERE inbox_id=? AND state IN ('pending','running')", (iid,)
        ).fetchone()
        if not live:
            self._insert_job(iid)

    def get(self, id: str) -> sqlite3.Row:
        row = self.conn.execute("SELECT * FROM inbox_items WHERE id=?", (id,)).fetchone()
        if row is None:
            raise KeyError(id)
        return row

    def list(self, status: str | None = None, limit: int = 200) -> list[sqlite3.Row]:
        where, args = ("WHERE status=?", [status]) if status else ("", [])
        return self.conn.execute(
            f"SELECT * FROM inbox_items {where} ORDER BY id DESC LIMIT ?", (*args, limit)
        ).fetchall()

    def retry(self, id: str) -> None:
        with self._tx():
            self.get(id)  # KeyError on unknown id
            self._requeue(id, utcnow())

    def set_status(self, id: str, status: str, error: str | None = None) -> None:
        self.conn.execute(
            "UPDATE inbox_items SET status=?, error=?, updated_at=? WHERE id=?",
            (str(status), error, utcnow(), id),
        )

    def add_event(self, inbox_id: str, stage: str, level: str, message: str,
                  data: dict | None = None, model: str | None = None) -> None:
        detail = message if data is None else f"{message} {json.dumps(data, default=str)}"
        self.conn.execute(
            "INSERT INTO processing_events(inbox_id, at, stage, status, detail, model) VALUES (?,?,?,?,?,?)",
            (inbox_id, utcnow(), stage, level, detail, model),
        )

    def clarify(self, id: str, text: str) -> None:
        with self._tx():
            self.get(id)  # KeyError on unknown id
            now = utcnow()
            self._append_context(id, text, now)
            # explicit record: the runner uses ONLY the latest clarification as content (never submit-time context)
            self.add_event(id, "clarified", "info", text)
            self._requeue(id, now)
