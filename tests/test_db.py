from infoparser.store.db import connect, migrate

TABLES = {
    "inbox_items", "jobs", "processing_events", "sources", "segments",
    "knowledge_items", "knowledge_versions", "topics", "entities",
    "item_topics", "item_entities", "relations", "embeddings",
    "provenance_log", "segments_fts", "items_fts",
}


def test_migrate_fresh_creates_all_tables(tmp_path):
    conn = connect(tmp_path / "t.db")
    assert migrate(conn) == 2
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
    names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master")}
    assert TABLES <= names
    conn.execute("INSERT INTO segments_fts(rowid, text) VALUES (1, 'hello world')")
    assert conn.execute("SELECT rowid FROM segments_fts WHERE segments_fts MATCH 'hello'").fetchone()[0] == 1
    conn.execute("INSERT INTO items_fts(rowid, title, body) VALUES (1, 't', 'quick fox')")
    assert conn.execute("SELECT rowid FROM items_fts WHERE items_fts MATCH 'fox'").fetchone()[0] == 1


def test_migrate_idempotent(tmp_path):
    conn = connect(tmp_path / "t.db")
    assert migrate(conn) == 2
    assert migrate(conn) == 2


def test_wal_enabled(tmp_path):
    conn = connect(tmp_path / "t.db")
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_canonical_url_unique_among_non_duplicates(tmp_path):
    import sqlite3
    import pytest
    conn = connect(tmp_path / "t.db")
    migrate(conn)
    ins = ("INSERT INTO inbox_items(id, adapter, submitted_at, status, canonical_url, duplicate_of, updated_at)"
           " VALUES (?, 'x', 't', 'pending', 'http://a', ?, 't')")
    conn.execute(ins, ("1", None))
    conn.execute(ins, ("2", "1"))  # duplicates allowed
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(ins, ("3", None))


def test_migrate_concurrent_fresh_db(tmp_path):
    import threading

    path = tmp_path / "race.db"
    conns = [connect(path) for _ in range(2)]
    barrier, out, errs = threading.Barrier(2), [], []

    def go(c):
        barrier.wait()
        try:
            out.append(migrate(c))
        except Exception as e:  # noqa: BLE001
            errs.append(e)

    ts = [threading.Thread(target=go, args=(c,)) for c in conns]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errs and out == [2, 2]
