"""Doctor: environment, database, blobs, backends, egress and external-tool checks.

Design rules: takes a Config (not Services: building Services creates and migrates the
database, which a diagnostic must not do on an empty home and cannot do on a corrupt one);
opens the DB with mode=ro (on a WAL database SQLite may still create -wal/-shm sidecar files
when it reads; it never writes to the main database); every check is isolated so one failure
never aborts the report or raises; probes have a 3 s timeout and send only canned strings,
never user content; remote backends are never contacted; `cli` backends are never executed
(shutil.which only). Exit code is non-zero only when a check is ERROR (WARN is allowed).
Levels: OK, INFO, WARN, ERROR."""
from __future__ import annotations

import dataclasses
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from infoparser.backup import _sha_file, latest_schema
from infoparser.providers.locality import opener  # no redirects, no proxy
from infoparser.providers.registry import Registry

PROBE_TIMEOUT = 3
SAMPLE = 20
_HEX = re.compile(r"[0-9a-f]{64}")
TOOLS = (("yt-dlp", "yt_dlp_binary", ["--version"]), ("ffmpeg", "ffmpeg_binary", ["-version"]),
         ("tesseract", None, ["--version"]), ("whisper-cli", None, None),
         ("pdftotext", None, ["-v"]))
DATA = {"distill": "the extracted text of every item you add", "classify": "item text",
        "embed": "item text and your search queries",
        "rerank": "your search query and candidate passages",
        "transcribe": "audio of media items", "describe": "images", "ocr": "images",
        "answer": "your question and the retrieved excerpts"}
NOTE = ("Reports the routes configured here and the egress events this install logged. It "
        "cannot report what a remote provider logs or retains. ask/search egress is shown "
        "when it happens and is not stored.")


@dataclass
class Check:
    """One doctor finding: a name, a level (OK/INFO/WARN/ERROR), a detail line and extra data."""
    name: str
    level: str
    detail: str
    data: dict = field(default_factory=dict)


def exit_code(checks) -> int:
    """1 when any check is an ERROR, else 0."""
    return 1 if any(c.level == "ERROR" for c in checks) else 0


def _ro(cfg):
    return sqlite3.connect(f"file:{cfg.db_path}?mode=ro", uri=True, timeout=3)


def _py(_cfg):
    v = sys.version_info
    return Check("python", "OK" if v >= (3, 13) else "ERROR",
                 f"{v.major}.{v.minor}.{v.micro}" + ("" if v >= (3, 13) else " (3.13+ required)"))


def _fts5(_cfg):
    try:
        sqlite3.connect(":memory:").execute("CREATE VIRTUAL TABLE t USING fts5(x)")
        return Check("sqlite_fts5", "OK", f"FTS5 available (sqlite {sqlite3.sqlite_version})")
    except sqlite3.Error as e:
        return Check("sqlite_fts5", "ERROR", f"FTS5 unavailable: {e}")


def _perms(cfg):
    home = Path(cfg.home)
    if not home.exists():
        return Check("permissions", "INFO", f"{home} does not exist yet")
    bad = []
    if home.stat().st_mode & 0o077:
        bad.append(f"{home} is {oct(home.stat().st_mode & 0o777)} (want 0700)")
    tok = home / "http_token"
    if tok.exists() and tok.stat().st_mode & 0o077:
        bad.append(f"{tok} is {oct(tok.stat().st_mode & 0o777)} (want 0600)")
    return Check("permissions", "WARN" if bad else "OK",
                 "; ".join(bad) or "home 0700, token 0600 (where present)")


def _database(cfg):
    if not Path(cfg.db_path).exists():
        return Check("database", "WARN",
                     f"not initialized: no database at {cfg.db_path} (run `infoparser init`)")
    c = _ro(cfg)
    try:
        ic = c.execute("PRAGMA integrity_check").fetchone()[0]
        v = c.execute("PRAGMA user_version").fetchone()[0]
    finally:
        c.close()
    if ic != "ok":
        return Check("database", "ERROR", f"integrity_check failed: {ic[:200]}")
    if v > latest_schema():
        return Check("database", "ERROR",
                     f"schema v{v} is newer than this install (v{latest_schema()})")
    return Check("database", "OK" if v == latest_schema() else "WARN",
                 f"schema v{v}" + ("" if v == latest_schema()
                                   else f" (v{latest_schema()} available; "
                                        "it migrates on next start)"),
                 {"schema_version": v})


def _queue(cfg):
    c = _ro(cfg)
    try:
        inbox = dict(c.execute("SELECT status, count(*) FROM inbox_items GROUP BY status"))
        jobs = dict(c.execute("SELECT state, count(*) FROM jobs GROUP BY state"))
        items = c.execute(
            "SELECT count(*) FROM knowledge_items WHERE deleted_at IS NULL").fetchone()[0]
    finally:
        c.close()
    lvl = "WARN" if inbox.get("failed") or inbox.get("needs_clarification") else "OK"
    return Check("queue", lvl, f"{items} items; inbox {inbox or '{}'}; jobs {jobs or '{}'}",
                 {"inbox": inbox, "jobs": jobs, "items": items})


def _blob_files(cfg) -> dict[str, Path]:
    root = Path(cfg.blobs_dir)
    if not root.is_dir():
        return {}
    return {p.name: p for p in root.rglob("*") if p.is_file() and _HEX.fullmatch(p.name)}


def _referenced(cfg) -> set[str]:
    c = _ro(cfg)
    try:
        return {r[0] for q in ("SELECT blob_sha256 FROM inbox_items",
                               "SELECT blob_sha256 FROM sources")
                for r in c.execute(q) if r[0]}
    finally:
        c.close()


def _blobs(cfg, full=False):
    refs, files = _referenced(cfg), _blob_files(cfg)
    missing = sorted(refs - files.keys())
    pool = sorted(refs & files.keys())
    check = pool if full else pool[:SAMPLE]
    corrupt = [sha[:12] for sha in check if _sha_file(files[sha]) != sha]
    probs = [f"{len(missing)} referenced blob(s) missing" if missing else "",
             f"{len(corrupt)} corrupted blob(s): {', '.join(corrupt)}" if corrupt else ""]
    probs = [p for p in probs if p]
    ok_detail = (f"{len(check)} of {len(pool)} blob(s) verified by sha256"
                 + ("" if full else " (sample; --full checks all)"))
    return Check("blobs", "ERROR" if probs else "OK", "; ".join(probs) or ok_detail)


def _orphans(cfg):
    orphan_blobs = len(_blob_files(cfg).keys() - _referenced(cfg))
    c = _ro(cfg)
    try:
        rows = c.execute("SELECT count(*) FROM knowledge_items k WHERE k.source_id IS NOT NULL AND"
                         " NOT EXISTS (SELECT 1 FROM sources s WHERE s.id=k.source_id)"
                         ).fetchone()[0]
        rows += c.execute("SELECT count(*) FROM inbox_items i WHERE i.source_id IS NOT NULL AND"
                          " NOT EXISTS (SELECT 1 FROM sources s WHERE s.id=i.source_id)"
                          ).fetchone()[0]
    finally:
        c.close()
    bits = [f"{orphan_blobs} orphan blob(s)" if orphan_blobs else "",
            f"{rows} row(s) pointing at a missing source" if rows else ""]
    bits = [b for b in bits if b]
    return Check("orphans", "WARN" if bits else "OK", "; ".join(bits) or "no orphan blobs or rows")


def _auth(b) -> dict:
    """Authorization header for a local backend configured with a key (never logged/reported)."""
    key = os.environ.get(b.api_key_env) if getattr(b, "api_key_env", None) else None
    return {"Authorization": f"Bearer {key}"} if key else {}


def _why(e) -> str:
    """Short failure reason; a 30x is named as a refused redirect (the key must not follow it)."""
    if isinstance(e, urllib.error.HTTPError) and 300 <= e.code < 400:
        return f"redirect refused (HTTP {e.code}); doctor never follows redirects"
    return str(getattr(e, "reason", e))


def _http_get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    with opener(True).open(req, timeout=PROBE_TIMEOUT) as r:
        return r.status


def _probe_embeddings(b) -> str:
    """POST a canned string to /embeddings. -> the detail suffix for the report."""
    try:  # canned probe string; never user content
        req = urllib.request.Request(
            b.base_url.rstrip("/") + "/embeddings", method="POST",
            data=json.dumps({"model": b.embed_model, "input": ["doctor probe"]}).encode(),
            headers={"Content-Type": "application/json", **_auth(b)})
        with opener(True).open(req, timeout=PROBE_TIMEOUT) as r:
            r.read()
        return "; /embeddings ok"
    except (urllib.error.URLError, OSError, ValueError) as e:
        return f"; /embeddings failed ({_why(e)})"


def _probe_openai(name, head, b, base) -> Check:
    try:
        _http_get(b.base_url.rstrip("/") + "/models", _auth(b))
    except urllib.error.HTTPError as e:
        if 300 <= e.code < 400:
            return Check(name, "WARN", f"{head}; probe failed at {b.base_url}: {_why(e)}", base)
        if e.code in (401, 403):
            return Check(name, "WARN", f"{head}; reachability unknown "
                         f"(auth required: HTTP {e.code}; set the key env var)", base)
        # any other HTTP status still proves the server is up
    except (urllib.error.URLError, OSError, ValueError) as e:
        return Check(name, "WARN",
                     f"{head}; unreachable at {b.base_url}: {getattr(e, 'reason', e)}", base)
    extra = ""
    if getattr(b.capabilities, "embeddings", False) and getattr(b, "embed_model", None):
        extra = _probe_embeddings(b)
    return Check(name, "OK" if "failed" not in extra else "WARN",
                 f"{head}; reachable{extra}; JSON mode not probed", base)


def _probe_binary(name, head, b, base) -> Check:
    exe = b.binary
    miss = [] if shutil.which(exe) else [f"binary {exe!r} not found"]
    if b.type == "whisper_cpp" and not Path(b.model_path).expanduser().exists():
        miss.append(f"model file {b.model_path!r} not found")
    return Check(name, "WARN" if miss else "OK", f"{head}; " + ("; ".join(miss) or "binary found"),
                 base)


def _probe(b) -> Check:
    name, caps = f"backend:{b.name}", {k: v for k, v in dataclasses.asdict(b.capabilities).items()
                                       if v is True}
    base = {"type": b.type, "locality": b.locality, "capabilities": sorted(caps)}
    head = f"{b.type}, {b.locality}, caps: {', '.join(sorted(caps)) or '-'}"
    if b.locality == "remote":
        return Check(name, "INFO", f"{head}; not probed "
                     "(remote backends are never contacted by doctor)", base)
    if b.type == "openai_compat":
        return _probe_openai(name, head, b, base)
    if b.type == "cli":
        exe = b.command[0] if b.command else ""
        ok = bool(shutil.which(exe))
        return Check(name, "OK" if ok else "WARN",
                     f"{head}; command {exe!r} {'found' if ok else 'not found'} (not executed)",
                     base)
    if b.type in ("tesseract", "whisper_cpp"):
        return _probe_binary(name, head, b, base)
    return Check(name, "OK", head, base)


def _backends(cfg):
    try:
        reg = Registry.from_config(cfg)
    except Exception as e:  # pylint: disable=broad-exception-caught  # noqa: BLE001 - bad config is a finding
        return [Check("backends", "ERROR", f"configuration error: {e}")]
    out = [Check("backends", "OK",
                 f"{len(reg.backends)} configured (allow_remote={cfg.allow_remote})")]
    for b in reg.backends.values():
        try:
            out.append(_probe(b))
        except Exception as e:  # pylint: disable=broad-exception-caught  # noqa: BLE001 - one probe never aborts the report
            out.append(Check(f"backend:{b.name}", "WARN",
                             f"probe failed: {type(e).__name__}: {e}"))
    return out


def _egress_log(cfg) -> list[dict]:
    """Per-backend egress events from the local processing log (empty when unreadable)."""
    if not Path(cfg.db_path).exists():
        return []
    try:
        c = _ro(cfg)
        try:
            return [{"backend": r[0], "calls": r[1], "bytes_sent": r[2] or 0} for r in c.execute(
                "SELECT backend, count(*), sum(json_extract(detail,'$.bytes_sent'))"
                " FROM processing_events WHERE stage='egress' GROUP BY backend ORDER BY backend")]
        finally:
            c.close()
    except sqlite3.Error:
        return []


def egress_report(cfg) -> dict:
    """Which tasks route to remote backends and what would leave. Config + the local egress log."""
    try:
        reg = Registry.from_config(dataclasses.replace(cfg, allow_remote=True))
    except Exception as e:  # pylint: disable=broad-exception-caught  # noqa: BLE001 - reported, not raised
        return {"allow_remote": cfg.allow_remote, "error": str(e), "routes": {}, "logged": [],
                "note": NOTE}
    routes = {}
    for task, data in DATA.items():
        chain = reg.chain(task)
        remote = [b.name for b in chain if b.locality == "remote"]
        routes[task] = {"remote": remote,
                        "local": [b.name for b in chain if b.locality != "remote"],
                        "blocked": bool(remote) and not cfg.allow_remote,
                        "data": data if remote else None}
    return {"allow_remote": cfg.allow_remote, "routes": routes, "logged": _egress_log(cfg),
            "note": NOTE}


def render_egress(r: dict) -> str:
    """Human-readable egress report."""
    lines = [f"allow_remote: {r['allow_remote']}"]
    if r.get("error"):
        lines.append(f"configuration error: {r['error']}")
    for t, x in r["routes"].items():
        if x["remote"]:
            state = "BLOCKED (allow_remote=false: nothing is sent)" if x["blocked"] else "ACTIVE"
            lines.append(f"{t}: remote {', '.join(x['remote'])} {state}; would send {x['data']}")
        else:
            lines.append(f"{t}: local only")
    for e in r["logged"]:
        lines.append(f"logged: {e['backend']}: {e['calls']} call(s), {e['bytes_sent']} bytes sent")
    lines.append(r["note"])
    return "\n".join(lines)


def _egress(cfg):
    r = egress_report(cfg)
    active = [t for t, x in r["routes"].items() if x["remote"] and not x["blocked"]]
    blocked = [t for t, x in r["routes"].items() if x["blocked"]]
    detail = ((f"remote routes active for: {', '.join(active)}" if active
               else "no remote route is active")
              + (f"; configured but blocked by allow_remote=false: {', '.join(blocked)}"
                 if blocked else ""))
    return Check("egress", "WARN" if active else "OK", detail, r)


def _tool(cfg, label, attr, args) -> Check:
    exe = getattr(cfg, attr) if attr else label
    path = shutil.which(exe)
    if not path:
        return Check(f"tool:{label}", "WARN",
                     f"{exe!r} not found on PATH (features that need it are unavailable)")
    ver = ""
    if args is not None:
        try:
            p = subprocess.run([path, *args], capture_output=True, text=True, errors="replace",
                               timeout=PROBE_TIMEOUT, check=False)
            ver = ((p.stdout or p.stderr).strip().splitlines() or [""])[0][:100]
        except (OSError, subprocess.TimeoutExpired):
            ver = "version check failed"
    return Check(f"tool:{label}", "OK", f"{path} {ver}".strip())


def run(cfg, full: bool = False) -> list[Check]:
    """Run every check, never raising. -> the findings, in report order."""
    out: list[Check] = []

    def guard(name, fn, *a):
        try:
            r = fn(cfg, *a)
            out.extend(r if isinstance(r, list) else [r])
        except sqlite3.DatabaseError as e:
            out.append(Check(name, "ERROR", f"database unreadable: {e}"))
        except Exception as e:  # pylint: disable=broad-exception-caught  # noqa: BLE001 - never a traceback
            out.append(Check(name, "ERROR", f"check failed: {type(e).__name__}: {e}"))

    guard("python", _py)
    guard("sqlite_fts5", _fts5)
    guard("permissions", _perms)
    guard("database", _database)
    if any(c.name == "database" and c.level in ("OK", "WARN")
           and "not initialized" not in c.detail for c in out):
        guard("queue", _queue)
        guard("blobs", _blobs, full)
        guard("orphans", _orphans)
    guard("backends", _backends)
    guard("egress", _egress)
    for label, attr, args in TOOLS:
        guard(f"tool:{label}", _tool, label, attr, args)
    return out


def render(checks) -> str:
    """One `[LEVEL] name: detail` line per check."""
    return "\n".join(f"[{c.level:<5}] {c.name}: {c.detail}" for c in checks)


def to_json(checks) -> str:
    """The checks as a JSON document with an overall `ok` flag."""
    return json.dumps({"ok": exit_code(checks) == 0,
                       "checks": [dataclasses.asdict(c) for c in checks]}, indent=2, default=str)
