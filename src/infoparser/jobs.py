"""Durable job queue: leases, retries with backoff, and processing events."""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass

from infoparser.config import Config
from infoparser.ids import new_id, utcnow
from infoparser.store.db import transaction

_BACKOFF_BASE, _BACKOFF_CAP = 5, 3600  # seconds


def _at(offset: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + offset))


def log_event(conn: sqlite3.Connection, inbox_id: str, job_id: str | None,  # pylint: disable=too-many-arguments,too-many-positional-arguments  # table columns
              stage: str, level: str = "info", detail: str | None = None) -> None:
    """Append a row to processing_events (one column per argument; widely called)."""
    conn.execute(
        "INSERT INTO processing_events(inbox_id, job_id, at, stage, status, detail)"
        " VALUES (?,?,?,?,?,?)",
        (inbox_id, job_id, utcnow(), stage, level, detail),
    )


@dataclass
class Job:
    """A claimed unit of work."""

    id: str
    inbox_id: str
    kind: str
    attempts: int


class JobQueue:
    """SQLite-backed queue with lease-based claiming (safe for concurrent workers)."""

    def __init__(self, conn: sqlite3.Connection, cfg: Config):
        self.conn, self.cfg = conn, cfg

    def enqueue(self, inbox_id: str, kind: str = "process") -> str:
        """Insert a pending job unless a pending/running one exists (then return that id)."""
        with transaction(self.conn):
            live = self.conn.execute(
                "SELECT id FROM jobs WHERE inbox_id=? AND state IN ('pending','running')",
                (inbox_id,)
            ).fetchone()
            if live:
                return live["id"]
            jid = new_id()
            self.conn.execute("INSERT INTO jobs(id, inbox_id, kind) VALUES (?,?,?)",
                              (jid, inbox_id, kind))
            return jid

    def claim(self, worker_id: str) -> Job | None:
        """Lease the oldest runnable pending job to `worker_id`, or None."""
        with transaction(self.conn):
            now = utcnow()
            self._reclaim(now)
            row = self.conn.execute(
                "SELECT id, inbox_id, kind, attempts FROM jobs WHERE state='pending'"
                " AND (run_after IS NULL OR run_after<=?) ORDER BY id LIMIT 1", (now,)
            ).fetchone()
            if row is None:
                return None
            self.conn.execute(
                "UPDATE jobs SET state='running', attempts=attempts+1, worker_id=?,"
                " lease_expires_at=? WHERE id=?",
                (worker_id, _at(self.cfg.lease_seconds), row["id"]),
            )
            return Job(row["id"], row["inbox_id"], row["kind"], row["attempts"] + 1)

    def heartbeat(self, job_id: str) -> None:
        """Extend the lease of a running job."""
        self.conn.execute(
            "UPDATE jobs SET lease_expires_at=? WHERE id=? AND state='running'",
            (_at(self.cfg.lease_seconds), job_id),
        )

    def complete(self, job_id: str, worker_id: str | None = None) -> bool:
        """False if the job is no longer running under this worker (stale completion ignored)."""
        cur = self.conn.execute(
            "UPDATE jobs SET state='done', lease_expires_at=NULL, last_error=NULL"
            " WHERE id=? AND state='running' AND (? IS NULL OR worker_id=?)",
            (job_id, worker_id, worker_id)
        )
        return cur.rowcount == 1

    def fail(self, job_id: str, error: str, worker_id: str | None = None) -> str:
        """'retry' | 'dead' | 'stale' (job not running under this worker; nothing changed)."""
        with transaction(self.conn):
            row = self.conn.execute(
                "SELECT attempts FROM jobs WHERE id=? AND state='running'"
                " AND (? IS NULL OR worker_id=?)",
                (job_id, worker_id, worker_id),
            ).fetchone()
            if row is None:
                return "stale"
            attempts = row[0]
            if attempts >= self.cfg.max_attempts:
                self.conn.execute(
                    "UPDATE jobs SET state='failed', last_error=?, lease_expires_at=NULL"
                    " WHERE id=?", (error, job_id),
                )
                return "dead"
            delay = min(_BACKOFF_BASE * 2 ** (attempts - 1), _BACKOFF_CAP)
            self.conn.execute(
                "UPDATE jobs SET state='pending', last_error=?, lease_expires_at=NULL,"
                " run_after=? WHERE id=?",
                (error, _at(delay), job_id),
            )
            return "retry"

    def reclaim_expired(self) -> int:
        """Requeue (or fail) every job whose lease expired; returns how many."""
        with transaction(self.conn):
            return self._reclaim(utcnow())

    def _reclaim(self, now: str) -> int:
        """Expired leases go back to pending; a job that already used all attempts dies instead."""
        n = 0
        for r in self.conn.execute(
            "SELECT id, inbox_id, attempts FROM jobs WHERE state='running'"
            " AND lease_expires_at<=?", (now,)
        ).fetchall():
            n += 1
            if r["attempts"] >= self.cfg.max_attempts:
                err = "lease expired after max attempts"
                self.conn.execute("UPDATE jobs SET state='failed', last_error=?,"
                                  " lease_expires_at=NULL WHERE id=?", (err, r["id"]))
                self.conn.execute("UPDATE inbox_items SET status='failed', error=?, updated_at=?"
                                  " WHERE id=?", (err, now, r["inbox_id"]))
                log_event(self.conn, r["inbox_id"], r["id"], "dead", "error", err)
            else:
                self.conn.execute("UPDATE jobs SET state='pending', lease_expires_at=NULL"
                                  " WHERE id=?", (r["id"],))
                log_event(self.conn, r["inbox_id"], r["id"], "lease_expired", "warning",
                          "lease expired, requeued")
        return n
