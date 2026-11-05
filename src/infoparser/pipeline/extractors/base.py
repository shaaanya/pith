from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from infoparser.providers.ports import TimedText


class NeedsClarificationError(Exception):
    def __init__(self, reason: str, pasteable: bool = False):
        super().__init__(reason)
        self.reason = reason
        self.pasteable = pasteable  # True only when text the user pastes can actually solve the problem


@dataclass
class Extracted:
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
    row: object  # inbox_items row
    blobs: object
    registry: object
    cfg: object


EXTRACTORS: dict[str, Callable[[ExtractCtx], Extracted]] = {}


def register(*content_types: str):
    def deco(fn):
        for ct in content_types:
            EXTRACTORS[ct] = fn
        return fn
    return deco
