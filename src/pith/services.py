"""Wiring: one Services bundle (config, connection, blobs, inbox, queue, registry) per process."""

import sqlite3
from dataclasses import dataclass

from pith.config import Config
from pith.inbox.service import Inbox
from pith.jobs import JobQueue
from pith.providers.registry import Registry
from pith.store.blobs import BlobStore
from pith.store.db import connect, migrate


@dataclass
class Services:  # pylint: disable=too-many-instance-attributes  # the bundle is the point
    """Everything a pipeline run, worker or dashboard needs."""

    cfg: Config
    conn: sqlite3.Connection
    blobs: BlobStore
    inbox: Inbox
    queue: JobQueue
    registry: Registry


def build(cfg: Config) -> Services:
    """Open the database (migrating it) and build every service from the config."""
    fresh_home, fresh_db = not cfg.home.exists(), not cfg.db_path.exists()
    if fresh_home:  # a home we create is private (the database holds the user's notes)
        cfg.home.mkdir(parents=True, exist_ok=True, mode=0o700)
        cfg.home.chmod(0o700)
    conn = connect(cfg.db_path)
    if fresh_db:
        cfg.db_path.chmod(0o600)
    migrate(conn)
    blobs = BlobStore(cfg.blobs_dir)
    return Services(cfg, conn, blobs, Inbox(conn, blobs, cfg), JobQueue(conn, cfg),
                    Registry.from_config(cfg))
