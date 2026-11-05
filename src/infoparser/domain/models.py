from dataclasses import dataclass
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
