"""Backup / restore / verify.

Archive layout (.tar.gz): manifest.json, infoparser.db, blobs/<ab>/<cd>/<sha256>, vault/<any depth>.
The DB is a consistent snapshot taken with the sqlite3 backup API (safe while a worker writes), taken BEFORE the
blobs are copied: submit() writes the blob before its row, so every blob the snapshot references exists.
manifest.json: {schema_version, created_at, counts, blob_count, app_version, files: {member: sha256}}.
NOT included: http_token and other credentials (a restored install generates a fresh token), OS litter
(.DS_Store, Thumbs.db) and anything under blobs/ that is not a valid blob name.
backup() writes only members that `_accepted` (the predicate restore uses) and verifies the finished archive
before putting it in place, so a bit-rotted live blob fails the backup instead of surfacing at restore time.
Archives are created with mode 0600.

Restore never trusts the archive: members are whitelisted (regular files only; no absolute or ".." names, no links
or devices; member and size caps) and written by hand into a staging dir; every file's sha256 is checked against
the manifest, every blob against its own name and prefix, the DB with integrity_check, and referenced blobs must
be present. A DB whose own PRAGMA user_version is newer than this install is refused, older ones are migrated.
Swap (--force): the stage lives INSIDE the home (same filesystem, so renames are atomic), the old db*/blobs/vault
are RENAMED into home/.pre-restore-<id> (never deleted), the new ones renamed in, and on ANY exception
(KeyboardInterrupt included) the new ones are removed and the old ones renamed back. The pre-restore copy and the
stage are deleted only after the new data is in place. A running `infoparser run` (it holds the flock on
home/run.lock) blocks restore. Other files in the home are kept."""
import fcntl
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
_VAULT = re.compile(r"vault/[^\\\x00]+")  # any depth; containment, `..` and links are enforced separately
_MAX_MEMBER = 4 * 1024**3
MAX_MEMBERS = 1_000_000
MAX_TOTAL_BYTES = 256 * 1024**3
_JUNK = {".DS_Store", "Thumbs.db"}


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


def _accepted(name: str) -> bool:
    """The ONE predicate for legitimate archive members: backup writes only these, restore accepts only these."""
    if name in ("manifest.json", DB_NAME):
        return True
    if b := _BLOB.fullmatch(name):
        return name == f"blobs/{b[1][:2]}/{b[1][2:4]}/{b[1]}"
    return bool(_VAULT.fullmatch(name)) and not any(p in ("", ".", "..") for p in name.split("/"))


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
                name = f"{prefix}/{p.relative_to(root).as_posix()}"
                if (p.is_file() and not p.is_symlink() and p.name not in _JUNK
                        and not p.name.startswith(".tmp-") and _accepted(name)):
                    members[name] = p
        files = {n: _sha_file(p) for n, p in members.items()}
        manifest = {"schema_version": schema, "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "counts": counts, "blob_count": sum(1 for n in members if n.startswith("blobs/")),
                    "app_version": _app_version(), "files": files}
        part = dest.with_name(dest.name + ".part")
        fd = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.fchmod(fd, 0o600)
        try:
            with os.fdopen(fd, "wb") as fh, tarfile.open(fileobj=fh, mode="w:gz") as t:
                raw = json.dumps(manifest, indent=2).encode()
                ti = tarfile.TarInfo("manifest.json")
                ti.size, ti.mtime = len(raw), int(time.time())
                t.addfile(ti, io.BytesIO(raw))
                for n, p in members.items():
                    t.add(p, arcname=n, recursive=False)
            verify(part)  # a bit-rotted live blob must fail the backup, not surface at restore time
        except BaseException:
            part.unlink(missing_ok=True)
            raise
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
    if not _accepted(n):
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
    names, count, total = set(), 0, 0
    try:
        with t:
            for m in t:
                count += 1
                if count > MAX_MEMBERS:
                    raise RestoreError(f"archive has too many members (> {MAX_MEMBERS})")
                n = _safe_name(m)
                if m.isdir():
                    continue
                total += m.size
                if total > MAX_TOTAL_BYTES:
                    raise RestoreError(f"archive is too large (> {MAX_TOTAL_BYTES} bytes uncompressed)")
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
        if not isinstance(files, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in files.items()):
            raise TypeError("files must map member names to sha256 strings")
        if not isinstance(man.get("counts", {}), dict):
            raise TypeError("counts must be an object")
        man["blob_count"] = int(man.get("blob_count", 0))
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
        raise RestoreError(f"manifest.json missing or invalid: {e}") from e
    problems = []
    for n in sorted(names - {"manifest.json"}):
        if n not in files:
            problems.append(f"{n}: not listed in manifest")
        elif _sha_file(stage / n) != files[n]:
            problems.append(f"{n}: sha256 mismatch ({'blob ' if n.startswith('blobs/') else ''}corrupted)")
        elif (b := _BLOB.fullmatch(n)) and _sha_file(stage / n) != b[1]:
            problems.append(f"{n}: blob content does not match its sha256 name")
    for n in sorted(set(files) - names):
        problems.append(f"{n}: listed in manifest but missing from archive"
                        + (" (blob lost)" if n.startswith("blobs/") else ""))
    if DB_NAME not in names:
        problems.append("infoparser.db missing from archive")
    else:
        try:
            c = sqlite3.connect(stage / DB_NAME)
            try:
                dbv = c.execute("PRAGMA user_version").fetchone()[0]
                if dbv > latest_schema():  # the DB's own version decides, not the (forgeable) manifest
                    raise RestoreError(f"backup is from a newer schema ({dbv} > {latest_schema()}); upgrade infoparser first")
                man["db_schema_version"] = dbv
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
    man["schema_version"] = man["db_schema_version"]
    return man


def verify(archive: Path) -> dict:
    """Run every restore check without touching any home. -> manifest, or raises RestoreError."""
    with tempfile.TemporaryDirectory(prefix="ip-verify-") as td:
        return _extract_and_check(Path(archive), Path(td))


def _non_empty(home: Path) -> bool:
    return home.is_dir() and any(home.iterdir())


def _remove(p: Path) -> None:
    if p.is_dir() and not p.is_symlink():
        shutil.rmtree(p)
    elif p.exists() or p.is_symlink():
        p.unlink()


def restore(archive: Path, home: Path, force: bool = False) -> None:
    home = Path(home)
    if _non_empty(home) and not force:
        raise RestoreError(f"{home} is not empty; refusing to overwrite (use --force to replace the database, blobs and vault)")
    created_home = not home.exists()
    home.mkdir(parents=True, exist_ok=True)
    lockf = open(home / "run.lock", "a+")
    try:
        try:
            fcntl.flock(lockf, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lockf.seek(0)
            raise RestoreError(f"an infoparser is running for {home} (pid {lockf.read().strip() or '?'}); "
                               "stop it before restoring") from None
        tag = f"{time.strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:6]}"
        stage, pre = home / f".restore-stage-{tag}", home / f".pre-restore-{tag}"
        stage.mkdir()
        moved: list[str] = []   # old items renamed into `pre`
        placed: list[str] = []  # new items renamed into `home`
        try:
            man = _extract_and_check(Path(archive), stage)
            if man["db_schema_version"] < latest_schema():  # migrate forward in staging
                c = connect(stage / DB_NAME)
                try:
                    migrate(c)
                    c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                finally:
                    c.close()
            for f in stage.glob(f"{DB_NAME}-*"):
                f.unlink()
            pre.mkdir()
            for old in [*sorted(home.glob(f"{DB_NAME}*")), home / "blobs", home / "vault"]:
                if old.exists():  # includes stale -wal / -shm: they must never be replayed into the new DB
                    os.replace(old, pre / old.name)
                    moved.append(old.name)
            for name in (DB_NAME, "blobs", "vault"):
                if (stage / name).exists():
                    os.replace(stage / name, home / name)
                    placed.append(name)
            os.chmod(home, 0o700)
        except BaseException:
            for name in placed:
                _remove(home / name)
            for name in moved:
                os.replace(pre / name, home / name)  # if THIS fails the old data stays safe in `pre`
            if pre.exists() and not any(pre.iterdir()):
                pre.rmdir()  # everything is back where it was
            raise
        finally:
            if stage.exists():
                shutil.rmtree(stage)  # staged leftovers only; old data lives in `pre`
        if pre.exists():
            shutil.rmtree(pre)  # new data verified and in place
    finally:
        lockf.close()
        if created_home and not (home / DB_NAME).exists():
            shutil.rmtree(home)  # failed restore into a fresh home leaves nothing behind
