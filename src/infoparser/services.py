"""Wiring: one Services bundle (config, connection, blobs, inbox, queue, registry) per process."""

import sqlite3
from dataclasses import dataclass

from infoparser.config import Config
from infoparser.inbox.service import Inbox
from infoparser.jobs import JobQueue
from infoparser.providers.registry import Registry
from infoparser.store.blobs import BlobStore
from infoparser.store.db import connect, migrate


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
    conn = connect(cfg.db_path)
    migrate(conn)
    blobs = BlobStore(cfg.blobs_dir)
    return Services(cfg, conn, blobs, Inbox(conn, blobs, cfg), JobQueue(conn, cfg),
                    Registry.from_config(cfg))
