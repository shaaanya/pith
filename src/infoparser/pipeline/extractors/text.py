"""Extractor for plain text, notes and code."""
from infoparser.pipeline.extractors.base import (
    Extracted, ExtractCtx, NeedsClarificationError, register)


def _title(text: str) -> str:
    first = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    return first.lstrip("# ").strip()[:80] or "Untitled note"


@register("note", "text", "code")
def extract(ctx: ExtractCtx) -> Extracted:
    """Decode the pasted text or stored file into a note (size-capped, NULs removed)."""
    row = ctx.row
    sha = row["blob_sha256"]
    if sha:
        path = ctx.blobs.path(sha)
        if path.stat().st_size > ctx.cfg.max_fetch_bytes:
            raise NeedsClarificationError(
                f"file larger than max_fetch_bytes ({ctx.cfg.max_fetch_bytes})")
        text = path.read_bytes().decode("utf-8", errors="replace")
    else:
        text = row["payload_text"] or ""
    text = text.replace("\r\n", "\n").replace("\x00", "")
    if not text.strip():
        raise NeedsClarificationError("empty content: nothing to extract", pasteable=True)
    return Extracted(row["original_filename"] or _title(text), None, row["canonical_url"],
                     "note", text, original_sha=sha)
