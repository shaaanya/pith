"""Backup / restore / verify.

Archive layout (.tar.gz): manifest.json, infoparser.db, blobs/<ab>/<cd>/<sha256>, vault/<yyyy>/<file>.md.
The DB is a consistent snapshot taken with the sqlite3 backup API (safe while a worker writes), taken BEFORE the
blobs are copied: submit() writes the blob before its row, so every blob the snapshot references exists.
manifest.json: {schema_version, created_at, counts, blob_count, app_version, files: {member: sha256}}.
NOT included: http_token and other credentials (a restored install generates a fresh token).

Restore never trusts the archive: members are whitelisted (regular files under known prefixes; no absolute or ".."
names, no links or devices) and written by hand into a staging dir next to the home; every file's sha256 is checked
against the manifest, every blob against its own name, the DB with integrity_check/foreign_key_check, and referenced
blobs must be present. Newer schemas are refused, older ones migrated forward. Only then is the staging dir swapped
in; any failure leaves the target untouched. Stale -wal/-shm files are removed so they cannot be replayed into the
restored DB. --force replaces only infoparser.db*, blobs/, vault/; other files in the home are kept."""
import hashlib
import io
import json
import os
import re
import shutil
import sqlite3
import tarfile
import tempfile
import time
import uuid
from importlib import metadata
from pathlib import Path, PurePosixPath

from infoparser.store.db import _migrations, connect, migrate

DB_NAME = "infoparser.db"
_BLOB = re.compile(r"blobs/[0-9a-f]{2}/[0-9a-f]{2}/([0-9a-f]{64})")
_VAULT = re.compile(r"vault/[^/\\]+/[^/\\]+")
_MAX_MEMBER = 4 * 1024**3


class RestoreError(Exception):
    pass


def _sha_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _app_version() -> str:
    try:
        return metadata.version("infoparser")
    except metadata.PackageNotFoundError:
        return "0"


def latest_schema() -> int:
    return _migrations()[-1][0]


def backup(cfg, dest: Path) -> Path:
    """-> path of the .tar.gz. dest is a directory (a timestamped name is used) or a file path."""
    dest = Path(dest)
    if dest.suffixes[-2:] != [".tar", ".gz"]:
        dest.mkdir(parents=True, exist_ok=True)
        dest = dest / f"infoparser-backup-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{uuid.uuid4().hex[:6]}.tar.gz"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not Path(cfg.db_path).is_file():
        raise RestoreError(f"nothing to back up: no database at {cfg.db_path}")
    with tempfile.TemporaryDirectory(prefix="ip-backup-") as td:
        snap = Path(td) / DB_NAME
        src = sqlite3.connect(cfg.db_path, timeout=30)
        dst = sqlite3.connect(snap)
        try:
            src.backup(dst)  # one consistent snapshot, even with concurrent writers
        finally:
            src.close()
        counts = {t: dst.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
                  for t in ("inbox_items", "sources", "segments", "knowledge_items")}
        schema = dst.execute("PRAGMA user_version").fetchone()[0]
        if dst.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RestoreError("snapshot failed integrity_check; backup aborted")
        dst.execute("PRAGMA journal_mode=DELETE")
        dst.close()
        members: dict[str, Path] = {DB_NAME: snap}
        for root, prefix in ((Path(cfg.blobs_dir), "blobs"), (Path(cfg.vault_dir), "vault")):  # blobs AFTER the snapshot
            for p in sorted(root.rglob("*")) if root.is_dir() else []:
                if p.is_file() and not p.is_symlink() and not p.name.startswith(".tmp-"):
                    members[f"{prefix}/{p.relative_to(root).as_posix()}"] = p
        files = {n: _sha_file(p) for n, p in members.items()}
        manifest = {"schema_version": schema, "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "counts": counts, "blob_count": sum(1 for n in members if n.startswith("blobs/")),
                    "app_version": _app_version(), "files": files}
        part = dest.with_name(dest.name + ".part")
        with tarfile.open(part, "w:gz") as t:
            raw = json.dumps(manifest, indent=2).encode()
            ti = tarfile.TarInfo("manifest.json")
            ti.size, ti.mtime = len(raw), int(time.time())
            t.addfile(ti, io.BytesIO(raw))
            for n, p in members.items():
                t.add(p, arcname=n, recursive=False)
        os.replace(part, dest)
    return dest


def _safe_name(m: tarfile.TarInfo) -> str:
    n = m.name
    if not (m.isreg() or m.isdir()):
        raise RestoreError(f"refusing archive member {n!r}: links and special files are not allowed")
    if n.startswith("/") or "\\" in n or "\x00" in n or ".." in PurePosixPath(n).parts or re.match(r"^[A-Za-z]:", n):
        raise RestoreError(f"refusing unsafe archive path {n!r}")
    if m.isdir():
        return n
    if n not in ("manifest.json", DB_NAME) and not _BLOB.fullmatch(n) and not _VAULT.fullmatch(n):
        raise RestoreError(f"refusing unexpected archive member {n!r}")
    if m.size > _MAX_MEMBER:
        raise RestoreError(f"archive member {n!r} is too large")
    return n


def _extract_and_check(archive: Path, stage: Path) -> dict:
    """Extract into stage (empty dir) and verify everything. Returns the manifest or raises RestoreError."""
    try:
        t = tarfile.open(archive, "r:gz")
    except (tarfile.TarError, OSError, EOFError) as e:
        raise RestoreError(f"not a readable backup archive: {e}") from e
    names = set()
    try:
        with t:
            for m in t:
                n = _safe_name(m)
                if m.isdir():
                    continue
                out = (stage / n).resolve()
                if stage.resolve() not in out.parents:
                    raise RestoreError(f"refusing unsafe archive path {n!r}")
                out.parent.mkdir(parents=True, exist_ok=True)
                with t.extractfile(m) as src, open(out, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                names.add(n)
    except (tarfile.TarError, OSError, EOFError) as e:
        raise RestoreError(f"archive is corrupt: {e}") from e
    try:
        man = json.loads((stage / "manifest.json").read_text())
        files, schema = man["files"], int(man["schema_version"])
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise RestoreError(f"manifest.json missing or invalid: {e}") from e
    if schema > latest_schema():
        raise RestoreError(f"backup is from a newer schema ({schema} > {latest_schema()}); upgrade infoparser first")
    problems = []
    for n in sorted(names - {"manifest.json"}):
        if n not in files:
            problems.append(f"{n}: not listed in manifest")
        elif _sha_file(stage / n) != files[n]:
            problems.append(f"{n}: sha256 mismatch ({'blob ' if n.startswith('blobs/') else ''}corrupted)")
        elif (b := _BLOB.fullmatch(n)) and _sha_file(stage / n) != b[1]:
            problems.append(f"{n}: blob content does not match its sha256 name")
    for n in sorted(set(files) - names):
        problems.append(f"{n}: listed in manifest but missing from archive (blob/file lost)" if n.startswith("blobs/")
                        else f"{n}: listed in manifest but missing from archive")
    if DB_NAME not in names:
        problems.append("infoparser.db missing from archive")
    else:
        try:
            c = sqlite3.connect(stage / DB_NAME)
            try:
                if c.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    problems.append("database failed integrity_check")
                else:
                    refs = {r[0] for q in ("SELECT blob_sha256 FROM inbox_items", "SELECT blob_sha256 FROM sources")
                            for r in c.execute(q) if r[0]}
                    have = {b[1] for n in names if (b := _BLOB.fullmatch(n))}
                    problems += [f"blob {sha[:12]}... referenced by the database is missing" for sha in sorted(refs - have)]
            finally:
                c.close()
        except sqlite3.DatabaseError as e:
            problems.append(f"database unreadable: {e}")
    if problems:
        raise RestoreError("backup verification failed:\n  " + "\n  ".join(problems))
    return man


def verify(archive: Path) -> dict:
    """Run every restore check without touching any home. -> manifest, or raises RestoreError."""
    with tempfile.TemporaryDirectory(prefix="ip-verify-") as td:
        return _extract_and_check(Path(archive), Path(td))


def _non_empty(home: Path) -> bool:
    return home.is_dir() and any(home.iterdir())


def restore(archive: Path, home: Path, force: bool = False) -> None:
    home = Path(home)
    if _non_empty(home) and not force:
        raise RestoreError(f"{home} is not empty; refusing to overwrite (use --force to replace the database, blobs and vault)")
    home.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{home.name}.restore-", dir=home.parent))
    try:
        man = _extract_and_check(Path(archive), stage)
        if man["schema_version"] < latest_schema():  # migrate forward in staging
            c = connect(stage / DB_NAME)
            try:
                migrate(c)
                c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            finally:
                c.close()
        for f in stage.glob(f"{DB_NAME}-*"):
            f.unlink()
        home.mkdir(parents=True, exist_ok=True)
        os.chmod(home, 0o700)
        for p in [*home.glob(f"{DB_NAME}*")]:  # includes stale -wal / -shm
            p.unlink()
        for d in ("blobs", "vault"):
            shutil.rmtree(home / d, ignore_errors=True)
        os.replace(stage / DB_NAME, home / DB_NAME)
        for d in ("blobs", "vault"):
            if (stage / d).is_dir():
                os.replace(stage / d, home / d)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
