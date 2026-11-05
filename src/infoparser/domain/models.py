"""Core value types shared across the pipeline."""
from dataclasses import dataclass, field
from enum import StrEnum


class Status(StrEnum):
    """Lifecycle state of an inbox item."""
    NEW = "new"
    PENDING = "pending"
    PROCESSING = "processing"
    PROCESSED = "processed"
    FAILED = "failed"
    NEEDS_CLARIFICATION = "needs_clarification"


class Provenance(StrEnum):
    """How well a knowledge item is backed by its source."""
    STATED = "stated"
    INFERRED = "inferred"
    EXTERNAL = "external"


@dataclass(frozen=True)
class SubmitResult:
    """Outcome of an inbox submission."""
    id: str  # the record that holds this submission (existing one on duplicate)
    duplicate_of: str | None = None
    requeued: bool = False


@dataclass(frozen=True)
class SegmentIn:
    """One chunk of extracted text with its locator."""
    idx: int
    text: str
    locator: str


@dataclass
class Candidate:  # pylint: disable=too-many-instance-attributes  # flat record
    """A knowledge item proposed by the model, before validation and saving."""
    kind: str
    title: str
    body: str
    data: dict = field(default_factory=dict)
    provenance: str = "inferred"
    evidence: str | None = None
    segment_idx: int | None = None
    confidence: float | None = None
    entities: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
