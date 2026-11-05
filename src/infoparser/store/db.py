import re
import sqlite3
from contextlib import contextmanager
from importlib import resources
from pathlib import Path


def connect(path: Path | str) -> sqlite3.Connection:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    # isolation_level=None: autocommit, callers manage transactions (BEGIN IMMEDIATE)
    conn = sqlite3.connect(p, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _migrations() -> list[tuple[int, str]]:
    out = []
    for f in resources.files("infoparser.store").joinpath("migrations").iterdir():
        m = re.match(r"(\d+)_.*\.sql$", f.name)
        if m:
            out.append((int(m.group(1)), f.read_text()))
    return sorted(out)


@contextmanager
def transaction(conn: sqlite3.Connection):
    # connection is autocommit (isolation_level=None), so `with conn:` would not open a txn.
    # Re-entrant: inside an open transaction this joins it (outermost owner commits/rolls back).
    if conn.in_transaction:
        yield
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def migrate(conn: sqlite3.Connection) -> int:
    # take the write lock first, then read user_version: concurrent migrators serialize and the loser no-ops
    with transaction(conn):
        current = conn.execute("PRAGMA user_version").fetchone()[0]
        for version, sql in _migrations():
            if version <= current:
                continue
            for stmt in _split(sql):
                conn.execute(stmt)
            conn.execute(f"PRAGMA user_version={version}")
            current = version
    return current


def _split(sql: str) -> list[str]:
    # ponytail: splits on ';' at line end; fine while migrations have no triggers/BEGIN blocks
    return [s.strip() for s in re.split(r";[ \t]*\n", sql) if s.strip()]
