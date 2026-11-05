"""Worker: claims queued jobs, runs the processor with a heartbeat, records the outcome."""
from __future__ import annotations

import logging
import sqlite3
import threading
from collections.abc import Callable
from dataclasses import dataclass

from infoparser.domain.models import Status
from infoparser.inbox.service import Inbox
from infoparser.jobs import JobQueue, log_event
from infoparser.store.db import connect, transaction

log = logging.getLogger(__name__)


@dataclass
class Processed:
    """The item was processed successfully."""


@dataclass
class NeedsClarification:
    """The item cannot proceed without user input."""
    reason: str


@dataclass
class Failed:
    """Processing failed; the job may be retried."""
    error: str


Outcome = Processed | NeedsClarification | Failed
Processor = Callable[[str], Outcome]


class Worker:
    """Runs one job at a time from the queue, keeping its lease alive meanwhile."""
    def __init__(self, conn: sqlite3.Connection, inbox: Inbox, queue: JobQueue,
                 processor: Processor, worker_id: str = "w1"):
        self.conn, self.inbox, self.queue = conn, inbox, queue
        self.processor, self.worker_id = processor, worker_id
        self.heartbeat_seconds = queue.cfg.lease_seconds / 3

    def _heartbeat_loop(self, job_id: str, done: threading.Event) -> None:
        # own connection: a sqlite connection must not be shared with an in-flight
        # transaction on another thread
        q = JobQueue(connect(self.queue.cfg.db_path), self.queue.cfg)
        while not done.wait(self.heartbeat_seconds):
            try:
                q.heartbeat(job_id)
            except sqlite3.OperationalError:
                log.warning("heartbeat failed for %s", job_id, exc_info=True)
        q.conn.close()

    def run_once(self) -> bool:
        """Claim and process one job. -> False when the queue is empty."""
        job = self.queue.claim(self.worker_id)
        if job is None:
            return False
        self.inbox.set_status(job.inbox_id, Status.PROCESSING)
        self.conn.execute("UPDATE inbox_items SET attempts=? WHERE id=?",
                          (job.attempts, job.inbox_id))
        log_event(self.conn, job.inbox_id, job.id, "claimed", "info", self.worker_id)
        # Lease is kept alive by a daemon thread heartbeating every lease_seconds/3 while the
        # processor runs.
        done = threading.Event()
        hb = threading.Thread(target=self._heartbeat_loop, args=(job.id, done), daemon=True)
        hb.start()
        try:
            out = self.processor(job.inbox_id)
        except Exception as e:  # pylint: disable=broad-exception-caught  # noqa: BLE001
            # any processor bug becomes a retryable failure
            out = Failed(f"{type(e).__name__}: {e}")
        finally:
            done.set()
            hb.join()
        self._finish(job, out)
        return True

    def _finish(self, job, out: Outcome) -> None:
        """Job state, inbox status and event commit together or not at all."""
        wid, iid = self.worker_id, job.inbox_id
        with transaction(self.conn):
            if isinstance(out, (Processed, NeedsClarification)):
                if not self.queue.complete(job.id, wid):
                    self._stale(job)
                    return
                if isinstance(out, Processed):
                    self.inbox.set_status(iid, Status.PROCESSED)
                    log_event(self.conn, iid, job.id, "processed")
                else:
                    self.inbox.set_status(iid, Status.NEEDS_CLARIFICATION, out.reason)
                    log_event(self.conn, iid, job.id, "needs_clarification", "info", out.reason)
            else:
                verdict = self.queue.fail(job.id, out.error, wid)
                if verdict == "stale":
                    self._stale(job)
                    return
                dead = verdict == "dead"
                self.inbox.set_status(iid, Status.FAILED if dead else Status.PENDING, out.error)
                log_event(self.conn, iid, job.id, verdict, "error" if dead else "warning",
                          out.error)

    def _stale(self, job) -> None:
        log_event(self.conn, job.inbox_id, job.id, "stale_completion", "warning",
                  f"{self.worker_id} lost its lease; result discarded")

    def run_forever(self, poll_seconds: float = 2.0, stop: threading.Event | None = None) -> None:
        """Poll the queue until `stop` is set, sleeping poll_seconds when idle."""
        stop = stop or threading.Event()
        while not stop.is_set():
            try:
                busy = self.run_once()
            except sqlite3.OperationalError:
                log.warning("worker db error", exc_info=True)
                busy = False
            if not busy:
                stop.wait(poll_seconds)
