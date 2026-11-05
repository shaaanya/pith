"""Provider ports: the only provider surface domain/pipeline/retrieval code may import."""
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol


@dataclass(frozen=True)
class Capabilities:
    text: bool = False
    json_mode: bool = False
    vision: bool = False
    embeddings: bool = False
    rerank: bool = False
    transcribe: bool = False
    ocr: bool = False
    context_window: int = 8192


@dataclass
class GenResult:
    text: str
    model: str
    backend: str


@dataclass
class EmbedResult:
    model_id: str
    vectors: list[list[float]]


@dataclass
class TimedText:
    start: float
    end: float
    text: str


class Backend(Protocol):
    name: str
    locality: Literal["local", "remote"]
    capabilities: Capabilities


class TextGenerator(Backend, Protocol):
    def generate(self, messages: list[dict], *, json_schema: dict | None = None,
                 max_tokens: int | None = None) -> GenResult: ...


class Embedder(Backend, Protocol):
    def embed(self, texts: list[str]) -> EmbedResult: ...


class Reranker(Backend, Protocol):
    def rerank(self, query: str, docs: list[str]) -> list[float]: ...


class Transcriber(Backend, Protocol):
    def transcribe(self, path: Path, language: str | None = None) -> list[TimedText]: ...


class VisionDescriber(Backend, Protocol):
    def describe(self, images: list[Path], prompt: str) -> str: ...


class OCR(Backend, Protocol):
    def read(self, image: Path) -> str: ...


class CapabilityError(Exception):
    """Backend does not support the requested operation."""


class RemoteBlocked(Exception):
    """Remote backend used while [privacy] allow_remote is false."""


class ProviderError(Exception):
    """Backend call failed (HTTP error, timeout, bad output, non-zero exit)."""


def flatten_messages(messages: list[dict]) -> str:
    return "\n\n".join(f"{m['role']}: {m['content']}" for m in messages)


def schema_instruction(json_schema: dict) -> str:
    import json
    return ("Respond with ONLY a JSON object that conforms to this JSON schema, no prose:\n"
            + json.dumps(json_schema))
