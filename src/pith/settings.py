"""Settings the dashboard may edit: model backends, task routing, allow_remote.

They are written to the config file that was loaded (cfg.source, else <home>/config.toml). Only
backends, tasks and privacy.allow_remote are replaced; every other key is kept. Comments in a
hand-written file are lost on the first save (the previous file is kept as config.toml.bak).

Safety rules:
- A save is validated end to end (re-parse, load_config, Registry.from_config) BEFORE the file is
  replaced, so a bad save can never stop the next launch.
- Only UI_TYPES backends can be added or changed here. Types that name a program to execute (cli,
  tesseract, whisper_cpp) pass through untouched and can only be edited in the file, so a stolen
  dashboard token cannot turn into code execution.
- API keys are never accepted: a backend names an environment variable (api_key_env)."""
from __future__ import annotations

import dataclasses
import json
import os
import re
import shutil
import subprocess
import threading
import tomllib
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from pith.config import Config, load_config
from pith.inbox.ingest import LOOPBACK
from pith.providers.registry import Registry

_COMMON = {"type", "model", "timeout", "context_window", "base_url", "api_key_env"}
# editable backend type -> the spec keys the dashboard may set
UI_TYPES = {
    "openai_compat": _COMMON | {"locality", "embed_model", "capabilities", "transcribe_model",
                                "vision_model", "rerank_model"},
    "anthropic": _COMMON | {"max_tokens", "anthropic_version"},
    "heuristic": {"type"},
}
# starting points for "add backend" in the UI (the model is chosen there)
PRESETS = {
    "local": {"type": "openai_compat", "locality": "local", "context_window": 4096,
              "base_url": "http://localhost:11434/v1", "model": ""},
    "cloud": {"type": "anthropic", "model": "", "api_key_env": "ANTHROPIC_API_KEY"},
}
TASKS = ("distill", "classify", "answer", "embed", "rerank", "ocr", "transcribe", "describe")
_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,31}")
_BARE = re.compile(r"[A-Za-z0-9_-]+")
_LOCK = threading.Lock()


def _key(k: str) -> str:
    return k if _BARE.fullmatch(k) else json.dumps(k, ensure_ascii=False)


def _val(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int | float):
        return repr(v)
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, list):
        return "[" + ", ".join(_val(x) for x in v) + "]"
    raise TypeError(f"cannot write {type(v).__name__} as TOML")


def dumps(table: dict, path: tuple = ()) -> str:
    """Minimal TOML writer: scalars, lists of scalars, nested tables (no arrays of tables)."""
    plain = [(k, v) for k, v in table.items() if not isinstance(v, dict)]
    subs = [(k, v) for k, v in table.items() if isinstance(v, dict)]
    head = ["[" + ".".join(_key(p) for p in path) + "]"] if path and (plain or not subs) else []
    body = "\n".join(head + [f"{_key(k)} = {_val(v)}" for k, v in plain])
    return "\n\n".join(x for x in [body, *(dumps(v, (*path, k)) for k, v in subs)] if x)


_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,63}")  # no leading "-": never read as a flag
# subscription name -> (command builder, model required). The ONLY way the dashboard can create a
# cli backend: the client names the CLI and a model, the server writes the command.
SUBSCRIPTIONS = {
    "claude": (lambda m: ["claude", "-p", "--tools", "", "--no-session-persistence",
                          *(["--model", m] if m else [])], False),
    "codex": (lambda m: ["codex", "exec", "-m", m, "-c", "model_reasoning_effort=low",
                         "--sandbox", "read-only", "--ephemeral", "--skip-git-repo-check",
                         "--color", "never"], True),
}


def sub_spec(kind, model) -> dict:
    """Server-authored cli spec for a subscription CLI; ValueError on an unknown kind or bad model.
    Always remote (the text goes to the vendor), so allow_remote applies."""
    if kind not in SUBSCRIPTIONS:
        raise ValueError(f"subscription {kind!r} is not supported (known: {sorted(SUBSCRIPTIONS)})")
    build, needs_model = SUBSCRIPTIONS[kind]
    model = model.strip() if isinstance(model, str) else ""
    if (needs_model or model) and not _MODEL.fullmatch(model):
        raise ValueError(f"{kind}: choose a model (letters, digits, . _ : / -)")
    return {"type": "cli", "subscription": kind, "locality": "remote", "timeout": 300,
            "command": build(model), **({"model": model} if model else {})}


def view(cfg: Config) -> dict:
    """What the Settings tab shows and edits."""
    return {
        "path": str(cfg.source or cfg.home / "config.toml"),
        "allow_remote": cfg.allow_remote,
        "backends": {n: {"spec": s, "editable": s.get("type") in UI_TYPES
                         or s.get("subscription") in SUBSCRIPTIONS}
                     for n, s in cfg.backends.items()},
        "tasks": cfg.tasks,
        "types": {t: sorted(k) for t, k in UI_TYPES.items()},
        "task_names": list(TASKS),
        "presets": PRESETS,
        "subscriptions": sorted(SUBSCRIPTIONS),
    }


def _check(cfg: Config, body) -> tuple[dict, dict, bool]:
    """Validate the posted settings against the rules above; (backends, tasks, allow_remote)."""
    if not isinstance(body, dict):
        raise ValueError("expected a JSON object")
    backends, tasks, remote = body.get("backends"), body.get("tasks"), body.get("allow_remote")
    if not (isinstance(backends, dict) and isinstance(tasks, dict) and isinstance(remote, bool)):
        raise ValueError("expected backends (object), tasks (object) and allow_remote (boolean)")
    for name, spec in backends.items():
        if not _NAME.fullmatch(name):
            raise ValueError(f"backend name {name!r}: use letters, digits, - and _ (max 32)")
        if not isinstance(spec, dict):
            raise ValueError(f"backend {name!r} must be an object")
        if "subscription" in spec:  # the client's command (if any) is discarded and rebuilt
            backends[name] = sub_spec(spec["subscription"], spec.get("model"))
            continue
        allowed = UI_TYPES.get(spec.get("type"))
        if allowed is None:
            if spec != cfg.backends.get(name):
                raise ValueError(f"backend {name!r}: type {spec.get('type')!r} can only be set "
                                 f"in the config file ({cfg.source or 'config.toml'})")
        elif extra := sorted(set(spec) - allowed):
            raise ValueError(f"backend {name!r}: keys not editable here: {', '.join(extra)}")
    clean_tasks = {}
    for task, refs in tasks.items():
        if not isinstance(refs, list) or not all(isinstance(r, str) for r in refs):
            raise ValueError(f"tasks.{task} must be a list of backend names")
        if refs:
            clean_tasks[task] = refs
    return backends, clean_tasks, remote


def save(cfg: Config, body) -> Config:
    """Validate and write the settings; return the new Config. ValueError on anything unusable
    (the file is then untouched)."""
    backends, tasks, remote = _check(cfg, body)
    target = cfg.source or cfg.home / "config.toml"
    with _LOCK:
        try:
            raw = tomllib.loads(target.read_text(encoding="utf-8")) if target.is_file() else {}
        except (OSError, ValueError) as e:
            raise ValueError(f"cannot read {target}: {e}") from e
        raw["backends"], raw["tasks"] = backends, tasks
        raw.setdefault("privacy", {})["allow_remote"] = remote
        for k in ("backends", "tasks"):
            if not raw[k]:
                del raw[k]
        try:
            text = ("# Written by the Pith dashboard (Settings). Comments are not kept;\n"
                    "# the previous file is saved as config.toml.bak.\n" + dumps(raw) + "\n")
            if tomllib.loads(text) != raw:
                raise ValueError("round-trip mismatch")
        except (TypeError, ValueError) as e:
            raise ValueError(f"{target} uses TOML the dashboard cannot rewrite ({e}); "
                             "edit the file by hand") from e
        return _write(cfg, target, text)


def enable_channel(cfg: Config, name: str) -> Config:
    """Set `[channels.<name>] enabled = true` in the config file, keeping every other key. The
    previous file is kept as config.toml.bak; a file already enabling it is not touched."""
    target = cfg.source or cfg.home / "config.toml"
    with _LOCK:
        try:
            raw = tomllib.loads(target.read_text(encoding="utf-8")) if target.is_file() else {}
        except (OSError, ValueError) as e:
            raise ValueError(f"cannot read {target}: {e}") from e
        chans = raw.setdefault("channels", {})
        if not isinstance(chans, dict) or not isinstance(chans.setdefault(name, {}), dict):
            raise ValueError(f"{target}: [channels.{name}] is not a table; edit the file by hand")
        if chans[name].get("enabled") is True:
            return cfg
        chans[name]["enabled"] = True
        try:
            text = ("# Rewritten by pith (setup or dashboard Settings). Comments are not kept;\n"
                    "# the previous file is saved as config.toml.bak.\n" + dumps(raw) + "\n")
            if tomllib.loads(text) != raw:
                raise ValueError("round-trip mismatch")
        except (TypeError, ValueError) as e:
            raise ValueError(f"{target} uses TOML pith cannot rewrite ({e}); "
                             f"add [channels.{name}] enabled = true by hand") from e
        return _write(cfg, target, text)


def _write(cfg: Config, target: Path, text: str) -> Config:
    """Write `text` beside `target`, validate it as a real config, then atomically replace."""
    tmp = target.with_name(f".{target.name}.tmp{os.getpid()}")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        new = dataclasses.replace(
            load_config(tmp, {**os.environ, "PITH_HOME": str(cfg.home)}), source=target)
        Registry.from_config(new)  # ConfigError (a ValueError) on a bad backend or task reference
        if target.is_file():
            shutil.copy2(target, target.with_name(target.name + ".bak"))
        os.replace(tmp, target)
        return new
    except OSError as e:
        raise ValueError(f"cannot write {target}: {e}") from e
    finally:
        tmp.unlink(missing_ok=True)


# Subscription CLIs the dashboard knows by name. Fixed argv only: nothing from a request reaches a
# subprocess. "status" is a cheap login check that calls no model; None = cannot be checked.
CLI_PROVIDERS = {
    "claude": {"status": ["claude", "auth", "status"], "note": ""},
    "codex": {"status": ["codex", "login", "status"], "note": "pass an explicit -m model"},
    "gemini": {"status": None, "note": "personal Google accounts are rejected by gemini-cli "
                                       "(see docs/providers.md)"},
}


def _logged_in(name: str, argv: list[str]) -> bool | None:
    """True/False from the CLI's own status command; None if it cannot be run or understood."""
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if name == "claude":  # prints JSON with a loggedIn flag
        try:
            return bool(json.loads(p.stdout).get("loggedIn"))
        except (ValueError, AttributeError):
            return None
    return p.returncode == 0  # codex: exit 0 only when logged in


def detect() -> list[dict]:
    """Which subscription CLIs and local servers this machine has. Read-only, calls no model."""
    out = []
    for name, info in CLI_PROVIDERS.items():
        found = shutil.which(name)
        status = info["status"]
        out.append({"id": name, "kind": "subscription", "installed": bool(found),
                    "logged_in": _logged_in(name, status) if found and status else None,
                    "note": info["note"]})
    try:
        models = list_models("http://localhost:11434/v1")
    except ValueError:
        models = None
    out.append({"id": "ollama", "kind": "local", "installed": models is not None,
                "logged_in": None, "models": models or [], "note": ""})
    return out


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect could leave localhost, so none is followed."""

    def redirect_request(self, *_args, **_kw):
        return None


def list_models(base_url) -> list[str]:
    """Model ids a local OpenAI-compatible server offers (GET <base_url>/models). Loopback hosts
    only, no redirects: the dashboard must not become a general URL fetcher."""
    u = urlsplit(base_url if isinstance(base_url, str) else "")
    if u.scheme not in ("http", "https") or (u.hostname or "").lower() not in LOOPBACK:
        raise ValueError("model detection only works for a server on this machine (localhost)")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)
    try:
        with opener.open(base_url.rstrip("/") + "/models", timeout=3) as r:
            data = json.loads(r.read(1_000_000))
    except (OSError, urllib.error.URLError, ValueError) as e:
        raise ValueError(f"cannot read models from {base_url}: {e}") from e
    items = data.get("data") if isinstance(data, dict) else None
    ids = {m["id"] for m in items or [] if isinstance(m, dict) and isinstance(m.get("id"), str)}
    return sorted(ids)[:200]
