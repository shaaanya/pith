from dataclasses import dataclass, field
from enum import StrEnum


class Status(StrEnum):
    NEW = "new"
    PENDING = "pending"
    PROCESSING = "processing"
    PROCESSED = "processed"
    FAILED = "failed"
    NEEDS_CLARIFICATION = "needs_clarification"


class Provenance(StrEnum):
    STATED = "stated"
    INFERRED = "inferred"
    EXTERNAL = "external"


@dataclass(frozen=True)
class SubmitResult:
    id: str  # the record that holds this submission (existing one on duplicate)
    duplicate_of: str | None = None
    requeued: bool = False


@dataclass(frozen=True)
class SegmentIn:
    idx: int
    text: str
    locator: str


@dataclass
class Candidate:
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
