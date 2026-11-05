"""Extractor registry and the value types extractors exchange."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from infoparser.providers.ports import TimedText


class NeedsClarificationError(Exception):
    """The item cannot be extracted as is; the user must supply or fix something."""

    def __init__(self, reason: str, pasteable: bool = False):
        super().__init__(reason)
        self.reason = reason
        # True only when text the user pastes can actually solve the problem
        self.pasteable = pasteable


@dataclass
class Extracted:  # pylint: disable=too-many-instance-attributes  # flat record
    """Result of extraction: text plus provenance fields."""

    title: str | None
    author: str | None
    url: str | None
    content_type: str
    text: str
    timed: list[TimedText] | None = None
    sections: list[tuple[str, str]] | None = None  # (locator, text), chunked independently
    metadata: dict = field(default_factory=dict)
    original_sha: str | None = None
    extractor: str | None = None  # defaults to the content type


@dataclass
class ExtractCtx:
    """What an extractor gets: the inbox row and the shared services."""

    row: object  # inbox_items row
    blobs: object
    registry: object
    cfg: object


EXTRACTORS: dict[str, Callable[[ExtractCtx], Extracted]] = {}


def register(*content_types: str):
    """Decorator registering an extractor for the given content types."""

    def deco(fn):
        for ct in content_types:
            EXTRACTORS[ct] = fn
        return fn
    return deco
