"""Schema migration and sqlite invariants."""
import sqlite3
import threading

import pytest

from pith.store.db import connect, migrate

TABLES = {
    "inbox_items", "jobs", "processing_events", "sources", "segments",
    "knowledge_items", "knowledge_versions", "topics", "entities",
    "item_topics", "item_entities", "relations", "embeddings",
    "provenance_log", "segments_fts", "items_fts",
}


def test_migrate_fresh_creates_all_tables(tmp_path):
    """A fresh migrate creates every table and the FTS indexes work."""
    conn = connect(tmp_path / "t.db")
    assert migrate(conn) == 4
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 4
    names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master")}
    assert TABLES <= names
    conn.execute("INSERT INTO segments_fts(rowid, text) VALUES (1, 'hello world')")
    hit = conn.execute("SELECT rowid FROM segments_fts WHERE segments_fts MATCH 'hello'")
    assert hit.fetchone()[0] == 1
    conn.execute("INSERT INTO items_fts(rowid, title, body) VALUES (1, 't', 'quick fox')")
    hit = conn.execute("SELECT rowid FROM items_fts WHERE items_fts MATCH 'fox'")
    assert hit.fetchone()[0] == 1


def test_migrate_idempotent(tmp_path):
    """Migrating twice changes nothing."""
    conn = connect(tmp_path / "t.db")
    assert migrate(conn) == 4
    assert migrate(conn) == 4


def test_wal_enabled(tmp_path):
    """The connection uses WAL."""
    conn = connect(tmp_path / "t.db")
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_canonical_url_unique_among_non_duplicates(tmp_path):
    """Only one non-duplicate item may hold a canonical url."""
    conn = connect(tmp_path / "t.db")
    migrate(conn)
    ins = ("INSERT INTO inbox_items(id, adapter, submitted_at, status, canonical_url,"
           " duplicate_of, updated_at) VALUES (?, 'x', 't', 'pending', 'http://a', ?, 't')")
    conn.execute(ins, ("1", None))
    conn.execute(ins, ("2", "1"))  # duplicates allowed
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(ins, ("3", None))


def test_migrate_concurrent_fresh_db(tmp_path):
    """Two connections migrating one fresh db at once both succeed."""
    path = tmp_path / "race.db"
    conns = [connect(path) for _ in range(2)]
    barrier, out, errs = threading.Barrier(2), [], []

    def go(c):
        barrier.wait()
        try:
            out.append(migrate(c))
        # any failure in the thread is recorded and asserted on below
        except Exception as e:  # noqa: BLE001  # pylint: disable=broad-exception-caught
            errs.append(e)

    ts = [threading.Thread(target=go, args=(c,)) for c in conns]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not errs and out == [4, 4]


def test_knowledge_items_source_id_is_indexed(tmp_path):
    """knowledge_items.source_id has an index."""
    conn = connect(tmp_path / "t.db")
    migrate(conn)
    indexes = conn.execute("PRAGMA index_list(knowledge_items)").fetchall()
    cols = [[c[2] for c in conn.execute(f"PRAGMA index_info({i[1]})")] for i in indexes]
    assert ["source_id"] in cols
