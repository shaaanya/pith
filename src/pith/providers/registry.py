"""Backend registry. Maps config backend `type` -> "module:Class", imported lazily via importlib
so modules not yet shipped (tesseract/whisper_cpp/anthropic arrive in Task 9) never break a build
unless a config actually uses them.

Config shape: cfg.backends = {name: {"type": ..., ...spec}};
cfg.tasks = {task: ["name" | "name:model"]}.
Remote enforcement: chain() silently filters remote backends when allow_remote=False but records
each skip in Registry.skipped (shown by describe()); get()/_resolve() for an explicitly requested
remote backend raise RemoteBlocked. Backends do not check the flag themselves. An openai_compat
backend with no declared locality is remote unless its host is loopback (see locality.py).
Accepted spec keys per type are documented in each backend module's docstring.
"""
import importlib
import threading
from dataclasses import asdict

from ..config import Config, ConfigError
from . import egress
from .ports import Backend, RemoteBlocked

TYPES = {
    "openai_compat": "pith.providers.openai_compat:OpenAICompatBackend",
    "cli": "pith.providers.cli_backend:CliBackend",
    "heuristic": "pith.providers.heuristic:HeuristicBackend",
    "tesseract": "pith.providers.tesseract:TesseractBackend",
    "whisper_cpp": "pith.providers.whisper_cpp:WhisperCppBackend",
    "anthropic": "pith.providers.anthropic:AnthropicBackend",
}
# task -> required Capabilities field; unknown tasks need "text"
TASK_CAPABILITY = {"embed": "embeddings", "rerank": "rerank", "transcribe": "transcribe",
                   "ocr": "ocr", "describe": "vision"}
# task -> the port method that serves it (everything else is served by generate)
TASK_METHOD = {"embed": "embed", "rerank": "rerank", "transcribe": "transcribe", "ocr": "read",
               "describe": "describe"}
# declared capability -> the method a backend must really have to claim it
CAPABILITY_METHOD = {"text": "generate", "json_mode": "generate", "embeddings": "embed",
                     "rerank": "rerank", "transcribe": "transcribe", "ocr": "read",
                     "vision": "describe"}
IMPLICIT_LAST = {"text"}  # capabilities whose chains always end with the heuristic backend


def _build(name: str, spec: dict) -> Backend:
    t = spec.get("type")
    if t not in TYPES:
        raise ConfigError(f"backend {name!r}: unknown type {t!r} (known: {sorted(TYPES)})")
    for key in ("timeout", "context_window"):  # a string would only fail later, inside a call
        v = spec.get(key, 1)
        if isinstance(v, bool) or not isinstance(v, int | float) or v <= 0:
            raise ConfigError(f"backend {name!r}: {key} must be a positive number, got {v!r}")
    mod, cls = TYPES[t].split(":")
    try:
        klass = getattr(importlib.import_module(mod), cls)
    except ImportError as e:
        raise ConfigError(f"backend {name!r}: type {t!r} unavailable: {e}") from e
    try:
        b = klass.from_spec(name, spec)
    except (KeyError, TypeError, ValueError) as e:
        raise ConfigError(f"backend {name!r}: bad spec ({type(e).__name__}: {e})") from e
    b.type = t
    for cap, method in CAPABILITY_METHOD.items():
        if getattr(b.capabilities, cap) and not callable(getattr(b, method, None)):
            raise ConfigError(f"backend {name!r}: capability {cap!r} is not implemented by "
                             f"type {t!r} (it has no {method}())")
    if b.locality == "remote":
        egress.wrap_remote(b)
    return b


BLOCKED = "remote blocked: allow_remote=false"


class Registry:
    """The configured backends, the task routing and the remote-block policy."""

    def __init__(self, backends: dict[str, Backend], specs: dict[str, dict],
                 tasks: dict[str, list[str]], allow_remote: bool):
        self.backends, self.specs, self.tasks = backends, specs, tasks
        self.allow_remote = allow_remote
        self.derived: dict[str, Backend] = {}  # "name:model" overrides
        self._skips: dict[tuple[str, str], dict] = {}
        self._lock = threading.RLock()

    @property
    def skipped(self) -> list[dict]:
        """Backends filtered out of a chain, with the reason."""
        with self._lock:
            return list(self._skips.values())

    @classmethod
    def from_config(cls, cfg: Config) -> "Registry":
        """Build every configured backend; fail at load on any bad spec or task reference."""
        specs = {k: dict(v) for k, v in cfg.backends.items()}
        backends = {n: _build(n, s) for n, s in specs.items()}
        if not any(b.type == "heuristic" for b in backends.values()):
            backends.setdefault("heuristic", _build("heuristic", {"type": "heuristic"}))
        reg = cls(backends, specs, {k: list(v) for k, v in cfg.tasks.items()}, cfg.allow_remote)
        for task, refs in reg.tasks.items():  # fail at load, and build overrides eagerly
            for ref in refs:
                if ref.split(":", 1)[0] not in backends:
                    raise ConfigError(f"task {task!r}: unknown backend {ref!r}")
                reg._lookup(ref)
        return reg

    def _lookup(self, ref: str) -> Backend:
        """Backend for "name" or a derived "name:model" override."""
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
        """Backends that can serve the task, in order, minus remote ones when blocked."""
        cap = TASK_CAPABILITY.get(task, "text")
        # unrouted task: all configured, in config order
        refs = self.tasks.get(task) or list(self.specs)
        method = TASK_METHOD.get(task, "generate")
        out = [b for b in map(self._lookup, refs)
               if getattr(b.capabilities, cap) and callable(getattr(b, method, None))]
        if cap in IMPLICIT_LAST:  # heuristic always last, even if configured earlier
            h = next(b for b in self.backends.values() if b.type == "heuristic")
            out = [b for b in out if b.type != "heuristic"] + [h]
        allowed = []
        for b in out:
            if self.allow_remote or b.locality != "remote":
                allowed.append(b)
            else:
                with self._lock:
                    self._skips[(b.name, task)] = {
                        "name": b.name, "task": task, "reason": BLOCKED}
        return allowed

    def generators(self, task: str) -> list[Backend]:
        """chain(task) minus the extractive heuristic backend (it cannot answer questions)."""
        return [b for b in self.chain(task) if b.type != "heuristic"]

    def first(self, task: str) -> Backend | None:
        """The first usable backend for the task, or None."""
        c = self.chain(task)
        return c[0] if c else None

    def describe(self) -> list[dict]:
        """Per backend: type, locality, capabilities, routed tasks and why it is blocked."""
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
                 "blocked_reason": blocked.get(n),
                 "skipped": [s for s in self.skipped if s["name"] == n]}
                for n in names]
