"""Provider ports: the only provider surface domain/pipeline/retrieval code may import."""
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol


@dataclass(frozen=True)
class Capabilities:  # pylint: disable=too-many-instance-attributes  # one flag per capability
    """What a backend can do."""

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
    """Text generation output."""

    text: str
    model: str
    backend: str


@dataclass
class EmbedResult:
    """Embedding output with the model id that produced it."""

    model_id: str
    vectors: list[list[float]]


@dataclass
class TimedText:
    """A transcript segment with start/end seconds."""

    start: float
    end: float
    text: str


class Backend(Protocol):  # pylint: disable=too-few-public-methods  # marker protocol: attributes only
    """Common attributes of every backend."""

    name: str
    locality: Literal["local", "remote"]
    capabilities: Capabilities


class TextGenerator(Backend, Protocol):  # pylint: disable=too-few-public-methods  # one-method port
    """Chat/completion port."""

    def generate(self, messages: list[dict], *, json_schema: dict | None = None,
                 max_tokens: int | None = None) -> GenResult:
        """Generate a reply to the chat messages (JSON-only when a schema is given)."""


class Embedder(Backend, Protocol):  # pylint: disable=too-few-public-methods  # one-method port
    """Embedding port."""

    def embed(self, texts: list[str]) -> EmbedResult:
        """Embed each text; the result names the model."""


class Reranker(Backend, Protocol):  # pylint: disable=too-few-public-methods  # one-method port
    """Reranking port."""

    def rerank(self, query: str, docs: list[str]) -> list[float]:
        """Relevance score of each doc for the query."""


class Transcriber(Backend, Protocol):  # pylint: disable=too-few-public-methods  # one-method port
    """Speech-to-text port."""

    def transcribe(self, path: Path, language: str | None = None) -> list[TimedText]:
        """Timed transcript of an audio file."""


class VisionDescriber(Backend, Protocol):  # pylint: disable=too-few-public-methods  # one-method port
    """Image description port."""

    def describe(self, images: list[Path], prompt: str) -> str:
        """Describe the images following the prompt."""


class OCR(Backend, Protocol):  # pylint: disable=too-few-public-methods  # one-method port
    """Text-from-image port."""

    def read(self, image: Path) -> str:
        """Text found in the image."""


class CapabilityError(Exception):
    """Backend does not support the requested operation."""


class RemoteBlocked(Exception):
    """Remote backend used while [privacy] allow_remote is false."""


class ProviderError(Exception):
    """Backend call failed (HTTP error, timeout, bad output, non-zero exit)."""


def run_cli(name: str, argv: list[str], timeout: float, stdin: str | None = None):
    """Run a local command to completion; ProviderError on spawn failure, timeout or bad exit."""
    try:
        p = subprocess.run(argv, input=stdin, capture_output=True, text=True, errors="replace",
                           timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise ProviderError(f"{name}: {e}") from e
    if p.returncode != 0:
        raise ProviderError(f"{name}: exit {p.returncode}: {p.stderr.strip()[:300]}")
    return p


def flatten_messages(messages: list[dict]) -> str:
    """Chat messages as one `role: content` text block."""
    return "\n\n".join(f"{m['role']}: {m['content']}" for m in messages)


def schema_instruction(json_schema: dict) -> str:
    """Prompt text asking for JSON-only output conforming to the schema."""
    return ("Respond with ONLY a JSON object that conforms to this JSON schema, no prose:\n"
            + json.dumps(json_schema))
