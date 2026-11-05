"""Backend registry. Maps config backend `type` -> "module:Class", imported lazily via importlib
so modules not yet shipped (tesseract/whisper_cpp/anthropic arrive in Task 9) never break a build
unless a config actually uses them.

Config shape: cfg.backends = {name: {"type": ..., ...spec}}; cfg.tasks = {task: ["name" | "name:model"]}.
Remote enforcement: chain() silently filters remote backends when allow_remote=False but records
each skip in Registry.skipped (shown by describe()); get()/_resolve() for an explicitly requested
remote backend raise RemoteBlocked. Backends do not check the flag themselves.
Accepted spec keys per type are documented in each backend module's docstring.
"""
import importlib
import threading
from dataclasses import asdict

from ..config import Config
from . import egress
from .ports import Backend, RemoteBlocked

TYPES = {
    "openai_compat": "infoparser.providers.openai_compat:OpenAICompatBackend",
    "cli": "infoparser.providers.cli_backend:CliBackend",
    "heuristic": "infoparser.providers.heuristic:HeuristicBackend",
    "tesseract": "infoparser.providers.tesseract:TesseractBackend",
    "whisper_cpp": "infoparser.providers.whisper_cpp:WhisperCppBackend",
    "anthropic": "infoparser.providers.anthropic:AnthropicBackend",
}
# task -> required Capabilities field; unknown tasks need "text"
TASK_CAPABILITY = {"embed": "embeddings", "rerank": "rerank", "transcribe": "transcribe",
                   "ocr": "ocr", "describe": "vision"}
IMPLICIT_LAST = {"text"}  # capabilities whose chains always end with the heuristic backend


def _build(name: str, spec: dict) -> Backend:
    t = spec.get("type")
    if t not in TYPES:
        raise ValueError(f"backend {name!r}: unknown type {t!r} (known: {sorted(TYPES)})")
    mod, cls = TYPES[t].split(":")
    try:
        klass = getattr(importlib.import_module(mod), cls)
    except ImportError as e:
        raise ValueError(f"backend {name!r}: type {t!r} unavailable: {e}") from e
    try:
        b = klass.from_spec(name, spec)
    except (KeyError, TypeError, ValueError) as e:
        raise ValueError(f"backend {name!r}: bad spec ({type(e).__name__}: {e})") from e
    b.type = t
    if b.locality == "remote":
        egress.wrap_remote(b)
    return b


BLOCKED = "remote blocked: allow_remote=false"


class Registry:
    def __init__(self, backends: dict[str, Backend], specs: dict[str, dict],
                 tasks: dict[str, list[str]], allow_remote: bool):
        self.backends, self.specs, self.tasks, self.allow_remote = backends, specs, tasks, allow_remote
        self.derived: dict[str, Backend] = {}  # "name:model" overrides
        self._skips: dict[tuple[str, str], dict] = {}
        self._lock = threading.RLock()

    @property
    def skipped(self) -> list[dict]:
        with self._lock:
            return list(self._skips.values())

    @classmethod
    def from_config(cls, cfg: Config) -> "Registry":
        specs = {k: dict(v) for k, v in cfg.backends.items()}
        backends = {n: _build(n, s) for n, s in specs.items()}
        if not any(b.type == "heuristic" for b in backends.values()):
            backends.setdefault("heuristic", _build("heuristic", {"type": "heuristic"}))
        reg = cls(backends, specs, {k: list(v) for k, v in cfg.tasks.items()}, cfg.allow_remote)
        for task, refs in reg.tasks.items():  # fail at load, and build overrides eagerly
            for ref in refs:
                if ref.split(":", 1)[0] not in backends:
                    raise ValueError(f"task {task!r}: unknown backend {ref!r}")
                reg._lookup(ref)
        return reg

    def _lookup(self, ref: str) -> Backend:
        name, _, model = ref.partition(":")
        if not model:
            return self.backends[name]
        with self._lock:
            if ref not in self.derived:  # "name:model" overrides spec["model"]
                self.derived[ref] = _build(name, {**self.specs[name], "model": model})
            return self.derived[ref]

    def _resolve(self, ref: str) -> Backend:
        """Explicit use of a backend: raises RemoteBlocked if remote and not allowed."""
        b = self._lookup(ref)
        if b.locality == "remote" and not self.allow_remote:
            raise RemoteBlocked(f"{ref}: {BLOCKED}")
        return b

    get = _resolve

    def chain(self, task: str) -> list[Backend]:
        cap = TASK_CAPABILITY.get(task, "text")
        refs = self.tasks.get(task) or list(self.specs)  # unrouted task: all configured, config order
        out = [b for b in map(self._lookup, refs) if getattr(b.capabilities, cap)]
        if cap in IMPLICIT_LAST:  # heuristic always last, even if configured earlier
            h = next(b for b in self.backends.values() if b.type == "heuristic")
            out = [b for b in out if b.type != "heuristic"] + [h]
        allowed = []
        for b in out:
            if self.allow_remote or b.locality != "remote":
                allowed.append(b)
            else:
                with self._lock:
                    self._skips[(b.name, task)] = {"name": b.name, "task": task, "reason": BLOCKED}
        return allowed

    def generators(self, task: str) -> list[Backend]:
        """chain(task) minus the extractive heuristic backend (it cannot answer questions)."""
        return [b for b in self.chain(task) if b.type != "heuristic"]

    def first(self, task: str) -> Backend | None:
        c = self.chain(task)
        return c[0] if c else None

    def describe(self) -> list[dict]:
        names = [*self.backends]
        route = {n: [] for n in names}
        for t in {*self.tasks, *TASK_CAPABILITY}:
            for b in self.chain(t):
                if b.name in route and self.backends[b.name] is b:
                    route[b.name].append(t)
        blocked = {}
        for sk in self.skipped:
            blocked[sk["name"]] = sk["reason"]
        return [{"name": n, "type": self.backends[n].type, "locality": self.backends[n].locality,
                 "capabilities": asdict(self.backends[n].capabilities), "tasks": sorted(route[n]),
                 "blocked_reason": blocked.get(n), "skipped": [s for s in self.skipped if s["name"] == n]}
                for n in names]
