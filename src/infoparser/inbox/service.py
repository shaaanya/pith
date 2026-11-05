"""Inbox: submit, de-duplicate, requeue and annotate inbox items."""
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
    """Everything submitted to infoparser, with its status, context and job."""
    def __init__(self, conn: sqlite3.Connection, blobs: BlobStore, cfg: Config):
        self.conn, self.blobs, self.cfg = conn, blobs, cfg

    def _tx(self):
        return transaction(self.conn)

    def submit(  # pylint: disable=too-many-arguments,too-many-locals  # keyword-only adapter API
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
        as_note: bool = False,
    ) -> SubmitResult:
        """external_id: adapter-scoped stable id (e.g. Telegram chat:message).

        A repeat with the same (adapter, external_id) is a pure no-op duplicate: no new row, no
        context appended, no requeue.

        as_note: keep a bare-URL text as a note (verbatim, never fetched or URL-deduped)."""
        if (text is None) == (file is None):
            raise ValueError("exactly one of text or file is required")
        kind, sha, url = self._classify(text, file, as_note)
        now = utcnow()
        with self._tx():
            dup = self._existing((adapter, external_id), (url, text), sha, user_context, now)
            if dup:
                return dup
            iid = new_id()
            self.conn.execute(
                "INSERT INTO inbox_items(id, adapter, platform, submitted_at, kind_hint,"
                " payload_text, blob_sha256, original_filename, mime, canonical_url,"
                " user_context, status, updated_at, external_id)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (iid, adapter, platform or detect_platform(url), now, kind, text, sha, filename,
                 mime, url, user_context or None, Status.PENDING, now, external_id),
            )
            self._insert_job(iid)
            self._record_external(adapter, external_id, iid)
        return SubmitResult(iid)

    def _classify(self, text: str | None, file: Path | bytes | None, as_note: bool = False):
        """-> (kind, blob sha256 or None, canonical url or None); stores the blob first."""
        if file is not None:
            # blob first: content-addressed and idempotent, so an orphan after rollback is harmless
            put = self.blobs.put_bytes if isinstance(file, bytes) else self.blobs.put_file
            return "file", put(file), None
        if not as_note and _BARE_URL.fullmatch(text.strip()):
            return "url", None, canonicalize_url(text)
        return "text", None, None

    def _seen_external(self, adapter: str, external_id: str | None) -> str | None:
        """The inbox id already recorded for (adapter, external_id), if any."""
        if not external_id:
            return None
        seen = self.conn.execute(
            "SELECT inbox_id AS id FROM external_ids WHERE adapter=? AND external_id=?",
            (adapter, external_id)).fetchone()
        return seen["id"] if seen else None

    # pylint: disable-next=too-many-arguments,too-many-positional-arguments  # one dedupe lookup; args are already grouped
    def _existing(self, ext: tuple, urls: tuple, sha, user_context, now) -> SubmitResult | None:
        """A repeat submission: no-op for a known external id, else folded into the original.

        ext is (adapter, external_id); urls is (canonical url or None, submitted text); the
        canonical form is only the lookup key, provenance records the URL as submitted."""
        url, text = urls
        adapter, external_id = ext
        seen = self._seen_external(adapter, external_id)
        if seen:
            return SubmitResult(seen, seen, False)
        old = self._find_original(url, sha)
        if not old:
            return None
        requeue = old["status"] in _DEAD
        self._append_context(old["id"], user_context, now)
        self.conn.execute(
            "INSERT INTO provenance_log(source_id, inbox_id, url, added_at) VALUES (?,?,?,?)",
            (old["source_id"], old["id"], text.strip() if url else None, now),
        )
        if requeue:
            self._requeue(old["id"], now)
        self._record_external(adapter, external_id, old["id"])
        return SubmitResult(old["id"], old["id"], requeue)

    def _find_original(self, url: str | None, sha: str | None):
        """The earliest non-duplicate row with this canonical url or blob, else None."""
        if url:
            q, key = "canonical_url=?", url
        elif sha:
            q, key = "blob_sha256=?", sha
        else:
            return None
        return self.conn.execute(
            f"SELECT * FROM inbox_items WHERE {q} AND duplicate_of IS NULL "
            "ORDER BY submitted_at LIMIT 1", (key,)
        ).fetchone()

    def _record_external(self, adapter, external_id, iid) -> None:
        if external_id:
            self.conn.execute(
                "INSERT OR IGNORE INTO external_ids(adapter, external_id, inbox_id)"
                " VALUES (?,?,?)", (adapter, external_id, iid))

    def _append_context(self, iid: str, ctx: str | None, now: str) -> None:
        cur = self.conn.execute("SELECT user_context FROM inbox_items WHERE id=?",
                                (iid,)).fetchone()
        # block-wise match; ctx may itself hold blank lines
        have = "\n\n" + (cur["user_context"] or "") + "\n\n"
        if ctx and "\n\n" + ctx + "\n\n" not in have:
            self.conn.execute(
                "UPDATE inbox_items SET user_context = CASE WHEN user_context IS NULL"
                " OR user_context='' THEN ? ELSE user_context || char(10,10) || ? END,"
                " updated_at=? WHERE id=?",
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

    def get(self, item_id: str) -> sqlite3.Row:
        """One inbox row; KeyError on an unknown id."""
        row = self.conn.execute("SELECT * FROM inbox_items WHERE id=?", (item_id,)).fetchone()
        if row is None:
            raise KeyError(item_id)
        return row

    def list(self, status: str | None = None, limit: int = 200) -> list[sqlite3.Row]:
        """Newest-first inbox rows, optionally filtered by status."""
        where, args = ("WHERE status=?", [status]) if status else ("", [])
        return self.conn.execute(
            f"SELECT * FROM inbox_items {where} ORDER BY id DESC LIMIT ?", (*args, limit)
        ).fetchall()

    def retry(self, item_id: str) -> None:
        """Requeue an item (resets attempts and error)."""
        with self._tx():
            self.get(item_id)  # KeyError on unknown id
            self._requeue(item_id, utcnow())

    def set_status(self, item_id: str, status: str, error: str | None = None) -> None:
        """Set an item's status (and error text)."""
        self.conn.execute(
            "UPDATE inbox_items SET status=?, error=?, updated_at=? WHERE id=?",
            (str(status), error, utcnow(), item_id),
        )

    def add_event(  # pylint: disable=too-many-arguments,too-many-positional-arguments
            self, inbox_id: str, stage: str, level: str, message: str,
            data: dict | None = None, model: str | None = None) -> None:
        """Append a processing event; `data` is serialised onto the message."""
        detail = message if data is None else f"{message} {json.dumps(data, default=str)}"
        self.conn.execute(
            "INSERT INTO processing_events(inbox_id, at, stage, status, detail, model)"
            " VALUES (?,?,?,?,?,?)",
            (inbox_id, utcnow(), stage, level, detail, model),
        )

    def clarify(self, item_id: str, text: str) -> None:
        """Add the user's clarification and requeue the item."""
        with self._tx():
            self.get(item_id)  # KeyError on unknown id
            now = utcnow()
            self._append_context(item_id, text, now)
            # explicit record: the runner uses ONLY the latest clarification as content (never
            # submit-time context)
            self.add_event(item_id, "clarified", "info", text)
            self._requeue(item_id, now)
