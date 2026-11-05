from dataclasses import dataclass

from infoparser.config import Config
from infoparser.inbox.service import Inbox
from infoparser.jobs import JobQueue
from infoparser.providers.registry import Registry
from infoparser.store.blobs import BlobStore
from infoparser.store.db import connect, migrate


@dataclass
class Services:
    cfg: Config
    conn: object
    blobs: BlobStore
    inbox: Inbox
    queue: JobQueue
    registry: Registry


def build(cfg: Config) -> Services:
    conn = connect(cfg.db_path)
    migrate(conn)
    blobs = BlobStore(cfg.blobs_dir)
    return Services(cfg, conn, blobs, Inbox(conn, blobs, cfg), JobQueue(conn, cfg), Registry.from_config(cfg))
