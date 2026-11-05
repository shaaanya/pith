"""Backend registry. Maps config backend `type` -> "module:Class", imported lazily via importlib
so modules not yet shipped (tesseract/whisper_cpp/anthropic arrive in Task 9) never break a build
unless a config actually uses them.

Config shape: cfg.backends = {name: {"type": ..., ...spec}}; cfg.tasks = {task: ["name" | "name:model"]}.
Accepted spec keys per type are documented in each backend module's docstring.
"""
import importlib
from dataclasses import asdict

from ..config import Config
from .ports import Backend

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
    b = klass.from_spec(name, spec)
    b.type = t
    return b


class Registry:
    def __init__(self, backends: dict[str, Backend], specs: dict[str, dict],
                 tasks: dict[str, list[str]], allow_remote: bool):
        self.backends, self.specs, self.tasks, self.allow_remote = backends, specs, tasks, allow_remote

    @classmethod
    def from_config(cls, cfg: Config) -> "Registry":
        specs = {k: dict(v) for k, v in cfg.backends.items()}
        backends = {n: _build(n, s) for n, s in specs.items()}
        reg = cls(backends, specs, {k: list(v) for k, v in cfg.tasks.items()}, cfg.allow_remote)
        for task, refs in reg.tasks.items():  # fail at load, not at first use
            for ref in refs:
                if ref.split(":", 1)[0] not in backends:
                    raise ValueError(f"task {task!r}: unknown backend {ref!r}")
        if not any(b.type == "heuristic" for b in backends.values()):
            backends.setdefault("heuristic", _build("heuristic", {"type": "heuristic"}))
        return reg

    def _resolve(self, ref: str) -> Backend:
        name, _, model = ref.partition(":")
        if not model:
            return self.backends[name]
        key = f"{name}:{model}"  # "name:model" overrides spec["model"] on a derived instance
        if key not in self.backends:
            self.backends[key] = _build(name, {**self.specs[name], "model": model})
        return self.backends[key]

    def chain(self, task: str) -> list[Backend]:
        cap = TASK_CAPABILITY.get(task, "text")
        refs = self.tasks.get(task) or list(self.specs)  # unrouted task: all configured, config order
        out = [b for b in map(self._resolve, refs) if getattr(b.capabilities, cap)]
        if cap in IMPLICIT_LAST:
            h = next(b for b in self.backends.values() if b.type == "heuristic")
            if h not in out:
                out.append(h)
        return [b for b in out if self.allow_remote or b.locality != "remote"]

    def first(self, task: str) -> Backend | None:
        c = self.chain(task)
        return c[0] if c else None

    def describe(self) -> list[dict]:
        route = {n: [t for t in {*self.tasks, *TASK_CAPABILITY} if any(b.name == n for b in self.chain(t))]
                 for n in self.backends if ":" not in n}
        return [{"name": n, "type": b.type, "locality": b.locality,
                 "capabilities": asdict(b.capabilities),
                 "tasks": sorted(route[n])}
                for n, b in self.backends.items() if ":" not in n]
