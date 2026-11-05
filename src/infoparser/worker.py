from __future__ import annotations

import sqlite3
import threading
from collections.abc import Callable
from dataclasses import dataclass

from infoparser.domain.models import Status
from infoparser.inbox.service import Inbox
from infoparser.ids import utcnow
from infoparser.jobs import JobQueue


@dataclass
class Processed:
    pass


@dataclass
class NeedsClarification:
    reason: str


@dataclass
class Failed:
    error: str


Outcome = Processed | NeedsClarification | Failed
Processor = Callable[[str], Outcome]


class Worker:
    def __init__(self, conn: sqlite3.Connection, inbox: Inbox, queue: JobQueue,
                 processor: Processor, worker_id: str = "w1"):
        self.conn, self.inbox, self.queue = conn, inbox, queue
        self.processor, self.worker_id = processor, worker_id

    def _event(self, job, stage: str, detail: str | None = None) -> None:
        self.conn.execute(
            "INSERT INTO processing_events(inbox_id, job_id, at, stage, status, detail)"
            " VALUES (?,?,?,?,?,?)",
            (job.inbox_id, job.id, utcnow(), stage, "info", detail),
        )

    def run_once(self) -> bool:
        job = self.queue.claim(self.worker_id)
        if job is None:
            return False
        self.inbox.set_status(job.inbox_id, Status.PROCESSING)
        self.conn.execute("UPDATE inbox_items SET attempts=? WHERE id=?", (job.attempts, job.inbox_id))
        self._event(job, "claimed", self.worker_id)
        try:
            out = self.processor(job.inbox_id)
        except Exception as e:  # noqa: BLE001 - any processor bug becomes a retryable failure
            out = Failed(f"{type(e).__name__}: {e}")
        if isinstance(out, Processed):
            self.queue.complete(job.id)
            self.inbox.set_status(job.inbox_id, Status.PROCESSED)
            self._event(job, "processed")
        elif isinstance(out, NeedsClarification):
            self.queue.complete(job.id)
            self.inbox.set_status(job.inbox_id, Status.NEEDS_CLARIFICATION, out.reason)
            self._event(job, "needs_clarification", out.reason)
        else:
            verdict = self.queue.fail(job.id, out.error)
            status = Status.FAILED if verdict == "dead" else Status.PENDING
            self.inbox.set_status(job.inbox_id, status, out.error)
            self._event(job, verdict, out.error)
        return True

    def run_forever(self, poll_seconds: float = 2.0, stop: threading.Event | None = None) -> None:
        stop = stop or threading.Event()
        while not stop.is_set():
            if not self.run_once():
                stop.wait(poll_seconds)

