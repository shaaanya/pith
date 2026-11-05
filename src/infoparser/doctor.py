"""Doctor: environment, database, blobs, backends, egress and external-tool checks.

Design rules: takes a Config (not Services: building Services creates and migrates the database, which a
diagnostic must not do on an empty home and cannot do on a corrupt one); opens the DB read-only; every check is
isolated so one failure never aborts the report or raises; probes have a 3 s timeout and send only canned
strings, never user content; remote backends are never contacted; `cli` backends are never executed
(shutil.which only). Exit code is non-zero only when a check is ERROR (WARN is allowed).
Levels: OK, INFO, WARN, ERROR."""
from __future__ import annotations

import dataclasses
import hashlib
import json
import re
import shutil
import sqlite3
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

PROBE_TIMEOUT = 3
SAMPLE = 20
_HEX = re.compile(r"[0-9a-f]{64}")
TOOLS = (("yt-dlp", "yt_dlp_binary", ["--version"]), ("ffmpeg", "ffmpeg_binary", ["-version"]),
         ("tesseract", None, ["--version"]), ("whisper-cli", None, None), ("pdftotext", None, ["-v"]))
DATA = {"distill": "the extracted text of every item you add", "classify": "item text",
        "embed": "item text and your search queries", "rerank": "your search query and candidate passages",
        "transcribe": "audio of media items", "describe": "images", "ocr": "images",
        "answer": "your question and the retrieved excerpts"}
NOTE = ("Reports the routes configured here and the egress events this install logged. It cannot report what a "
        "remote provider logs or retains. ask/search egress is shown when it happens and is not stored.")


@dataclass
class Check:
    name: str
    level: str
    detail: str
    data: dict = field(default_factory=dict)


def exit_code(checks) -> int:
    return 1 if any(c.level == "ERROR" for c in checks) else 0


def _ro(cfg):
    return sqlite3.connect(f"file:{cfg.db_path}?mode=ro", uri=True, timeout=3)


def _py(cfg):
    v = sys.version_info
    return Check("python", "OK" if v >= (3, 13) else "ERROR", f"{v.major}.{v.minor}.{v.micro}" + ("" if v >= (3, 13) else " (3.13+ required)"))


def _fts5(cfg):
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
    return Check("permissions", "WARN" if bad else "OK", "; ".join(bad) or "home 0700, token 0600 (where present)")


def _database(cfg):
    from infoparser.backup import latest_schema
    if not Path(cfg.db_path).exists():
        return Check("database", "WARN", f"not initialized: no database at {cfg.db_path} (run `infoparser init`)")
    c = _ro(cfg)
    try:
        ic = c.execute("PRAGMA integrity_check").fetchone()[0]
        v = c.execute("PRAGMA user_version").fetchone()[0]
    finally:
        c.close()
    if ic != "ok":
        return Check("database", "ERROR", f"integrity_check failed: {ic[:200]}")
    if v > latest_schema():
        return Check("database", "ERROR", f"schema v{v} is newer than this install (v{latest_schema()})")
    return Check("database", "OK" if v == latest_schema() else "WARN",
                 f"schema v{v}" + ("" if v == latest_schema() else f" (v{latest_schema()} available; it migrates on next start)"),
                 {"schema_version": v})


def _queue(cfg):
    c = _ro(cfg)
    try:
        inbox = {r[0]: r[1] for r in c.execute("SELECT status, count(*) FROM inbox_items GROUP BY status")}
        jobs = {r[0]: r[1] for r in c.execute("SELECT state, count(*) FROM jobs GROUP BY state")}
        items = c.execute("SELECT count(*) FROM knowledge_items WHERE deleted_at IS NULL").fetchone()[0]
    finally:
        c.close()
    lvl = "WARN" if inbox.get("failed") or inbox.get("needs_clarification") else "OK"
    return Check("queue", lvl, f"{items} items; inbox {inbox or '{}'}; jobs {jobs or '{}'}", {"inbox": inbox, "jobs": jobs, "items": items})


def _blob_files(cfg) -> dict[str, Path]:
    root = Path(cfg.blobs_dir)
    return {p.name: p for p in root.rglob("*") if p.is_file() and _HEX.fullmatch(p.name)} if root.is_dir() else {}


def _referenced(cfg) -> set[str]:
    c = _ro(cfg)
    try:
        return {r[0] for q in ("SELECT blob_sha256 FROM inbox_items", "SELECT blob_sha256 FROM sources")
                for r in c.execute(q) if r[0]}
    finally:
        c.close()


def _blobs(cfg, full=False):
    refs, files = _referenced(cfg), _blob_files(cfg)
    missing = sorted(refs - files.keys())
    pool = sorted(refs & files.keys())
    check = pool if full else pool[:SAMPLE]
    corrupt = []
    for sha in check:
        h = hashlib.sha256()
        with files[sha].open("rb") as f:
            for ch in iter(lambda: f.read(1 << 20), b""):
                h.update(ch)
        if h.hexdigest() != sha:
            corrupt.append(sha[:12])
    probs = [f"{len(missing)} referenced blob(s) missing" if missing else "",
             f"{len(corrupt)} corrupted blob(s): {', '.join(corrupt)}" if corrupt else ""]
    probs = [p for p in probs if p]
    return Check("blobs", "ERROR" if probs else "OK",
                 "; ".join(probs) or f"{len(check)} of {len(pool)} blob(s) verified by sha256" + ("" if full else " (sample; --full checks all)"))


def _orphans(cfg):
    orphan_blobs = len(_blob_files(cfg).keys() - _referenced(cfg))
    c = _ro(cfg)
    try:
        rows = c.execute("SELECT count(*) FROM knowledge_items k WHERE k.source_id IS NOT NULL AND"
                         " NOT EXISTS (SELECT 1 FROM sources s WHERE s.id=k.source_id)").fetchone()[0]
        rows += c.execute("SELECT count(*) FROM inbox_items i WHERE i.source_id IS NOT NULL AND"
                          " NOT EXISTS (SELECT 1 FROM sources s WHERE s.id=i.source_id)").fetchone()[0]
    finally:
        c.close()
    bits = [f"{orphan_blobs} orphan blob(s)" if orphan_blobs else "", f"{rows} row(s) pointing at a missing source" if rows else ""]
    bits = [b for b in bits if b]
    return Check("orphans", "WARN" if bits else "OK", "; ".join(bits) or "no orphan blobs or rows")


def _http_get(url, timeout=PROBE_TIMEOUT):
    with urllib.request.urlopen(url, timeout=timeout) as r:  # noqa: S310 - loopback/local backend, canned request
        return r.status


def _probe(cfg, b) -> Check:
    name, caps = f"backend:{b.name}", {k: v for k, v in dataclasses.asdict(b.capabilities).items() if v is True}
    base = {"type": b.type, "locality": b.locality, "capabilities": sorted(caps)}
    head = f"{b.type}, {b.locality}, caps: {', '.join(sorted(caps)) or '-'}"
    if b.locality == "remote":
        return Check(name, "INFO", f"{head}; not probed (remote backends are never contacted by doctor)", base)
    if b.type == "openai_compat":
        try:
            _http_get(b.base_url.rstrip("/") + "/models")
        except (urllib.error.URLError, OSError, ValueError) as e:
            return Check(name, "WARN", f"{head}; unreachable at {b.base_url}: {getattr(e, 'reason', e)}", base)
        extra = ""
        if getattr(b.capabilities, "embeddings", False) and getattr(b, "embed_model", None):
            try:  # canned probe string; never user content
                req = urllib.request.Request(b.base_url.rstrip("/") + "/embeddings", method="POST",
                                             data=json.dumps({"model": b.embed_model, "input": ["doctor probe"]}).encode(),
                                             headers={"Content-Type": "application/json"})
                urllib.request.urlopen(req, timeout=PROBE_TIMEOUT).read()  # noqa: S310
                extra = "; /embeddings ok"
            except (urllib.error.URLError, OSError, ValueError) as e:
                extra = f"; /embeddings failed ({getattr(e, 'reason', e)})"
        return Check(name, "OK" if "failed" not in extra else "WARN", f"{head}; reachable{extra}; JSON mode not probed", base)
    if b.type == "cli":
        exe = b.command[0] if b.command else ""
        ok = bool(shutil.which(exe))
        return Check(name, "OK" if ok else "WARN", f"{head}; command {exe!r} {'found' if ok else 'not found'} (not executed)", base)
    if b.type in ("tesseract", "whisper_cpp"):
        exe = b.binary
        ok = bool(shutil.which(exe))
        miss = [] if ok else [f"binary {exe!r} not found"]
        if b.type == "whisper_cpp" and not Path(b.model_path).expanduser().exists():
            miss.append(f"model file {b.model_path!r} not found")
        return Check(name, "WARN" if miss else "OK", f"{head}; " + ("; ".join(miss) or "binary found"), base)
    return Check(name, "OK", head, base)


def _backends(cfg):
    from infoparser.providers.registry import Registry
    try:
        reg = Registry.from_config(cfg)
    except Exception as e:  # noqa: BLE001 - a bad config is a finding, not a crash
        return [Check("backends", "ERROR", f"configuration error: {e}")]
    out = [Check("backends", "OK", f"{len(reg.backends)} configured (allow_remote={cfg.allow_remote})")]
    for b in reg.backends.values():
        try:
            out.append(_probe(cfg, b))
        except Exception as e:  # noqa: BLE001
            out.append(Check(f"backend:{b.name}", "WARN", f"probe failed: {type(e).__name__}: {e}"))
    return out


def egress_report(cfg) -> dict:
    """Which tasks route to remote backends and what would leave. Pure config + the local egress log."""
    from infoparser.providers.registry import Registry
    try:
        reg = Registry.from_config(dataclasses.replace(cfg, allow_remote=True))
    except Exception as e:  # noqa: BLE001
        return {"allow_remote": cfg.allow_remote, "error": str(e), "routes": {}, "logged": [], "note": NOTE}
    routes = {}
    for task in DATA:
        chain = reg.chain(task)
        remote = [b.name for b in chain if b.locality == "remote"]
        routes[task] = {"remote": remote, "local": [b.name for b in chain if b.locality != "remote"],
                        "blocked": bool(remote) and not cfg.allow_remote,
                        "data": DATA[task] if remote else None}
    logged = []
    if Path(cfg.db_path).exists():
        try:
            c = _ro(cfg)
            try:
                logged = [{"backend": r[0], "calls": r[1], "bytes_sent": r[2] or 0} for r in c.execute(
                    "SELECT backend, count(*), sum(json_extract(detail,'$.bytes_sent')) FROM processing_events"
                    " WHERE stage='egress' GROUP BY backend ORDER BY backend")]
            finally:
                c.close()
        except sqlite3.Error:
            pass
    return {"allow_remote": cfg.allow_remote, "routes": routes, "logged": logged, "note": NOTE}


def render_egress(r: dict) -> str:
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
    detail = (f"remote routes active for: {', '.join(active)}" if active else "no remote route is active") + \
             (f"; configured but blocked by allow_remote=false: {', '.join(blocked)}" if blocked else "")
    return Check("egress", "WARN" if active else "OK", detail, r)


def _tool(cfg, label, attr, args) -> Check:
    exe = getattr(cfg, attr) if attr else label
    path = shutil.which(exe)
    if not path:
        return Check(f"tool:{label}", "WARN", f"{exe!r} not found on PATH (features that need it are unavailable)")
    ver = ""
    if args is not None:
        try:
            p = subprocess.run([path, *args], capture_output=True, text=True, errors="replace", timeout=PROBE_TIMEOUT)
            ver = ((p.stdout or p.stderr).strip().splitlines() or [""])[0][:100]
        except (OSError, subprocess.TimeoutExpired):
            ver = "version check failed"
    return Check(f"tool:{label}", "OK", f"{path} {ver}".strip())


def run(cfg, full: bool = False) -> list[Check]:
    out: list[Check] = []

    def guard(name, fn, *a):
        try:
            r = fn(cfg, *a)
            out.extend(r if isinstance(r, list) else [r])
        except sqlite3.DatabaseError as e:
            out.append(Check(name, "ERROR", f"database unreadable: {e}"))
        except Exception as e:  # noqa: BLE001 - never a traceback
            out.append(Check(name, "ERROR", f"check failed: {type(e).__name__}: {e}"))

    guard("python", _py)
    guard("sqlite_fts5", _fts5)
    guard("permissions", _perms)
    guard("database", _database)
    if any(c.name == "database" and c.level in ("OK", "WARN") and "not initialized" not in c.detail for c in out):
        guard("queue", _queue)
        guard("blobs", _blobs, full)
        guard("orphans", _orphans)
    guard("backends", _backends)
    guard("egress", _egress)
    for label, attr, args in TOOLS:
        guard(f"tool:{label}", _tool, label, attr, args)
    return out


def render(checks) -> str:
    return "\n".join(f"[{c.level:<5}] {c.name}: {c.detail}" for c in checks)


def to_json(checks) -> str:
    return json.dumps({"ok": exit_code(checks) == 0, "checks": [dataclasses.asdict(c) for c in checks]}, indent=2, default=str)
