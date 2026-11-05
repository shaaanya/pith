from __future__ import annotations

import shutil
import subprocess

from infoparser.pipeline.extractors.base import Extracted, ExtractCtx, NeedsClarificationError, register

HINT = "no PDF reader; install pypdf (pip install pypdf) or poppler (pdftotext)"


def _pypdf_pages(path) -> list[str] | None:
    try:
        from pypdf import PdfReader  # optional extra, never imported at module top level
    except ImportError:
        return None
    return [(pg.extract_text() or "") for pg in PdfReader(str(path)).pages]


def _pdftotext_pages(path) -> list[str] | None:
    exe = shutil.which("pdftotext")
    if not exe:
        return None
    r = subprocess.run([exe, "-enc", "UTF-8", str(path), "-"], capture_output=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"pdftotext failed: {r.stderr.decode(errors='replace').strip()[:200]}")
    pages = r.stdout.decode("utf-8", errors="replace").split("\f")
    return pages[:-1] if pages and not pages[-1].strip() else pages


def available() -> bool:
    try:
        import pypdf  # noqa: F401
        return True
    except ImportError:
        return shutil.which("pdftotext") is not None


@register("pdf")
def extract(ctx: ExtractCtx) -> Extracted:
    sha = ctx.row["blob_sha256"]
    if not sha:
        raise NeedsClarificationError("pdf item has no file")
    path = ctx.blobs.path(sha)
    if path.stat().st_size > ctx.cfg.max_fetch_bytes:
        raise NeedsClarificationError(f"file larger than max_fetch_bytes ({ctx.cfg.max_fetch_bytes})")
    pages = _pypdf_pages(path)
    if pages is None:
        pages = _pdftotext_pages(path)
    if pages is None:
        raise NeedsClarificationError(HINT)
    sections = [(f"page={i}", t.replace("\x00", "").strip()) for i, t in enumerate(pages, 1) if t.strip()]
    if not sections:
        raise NeedsClarificationError("PDF has no text layer (scanned?); OCR for PDFs is not supported", pasteable=True)
    name = ctx.row["original_filename"] or "Untitled PDF"
    return Extracted(name, None, ctx.row["canonical_url"], "pdf", "\n\n".join(t for _, t in sections),
                     sections=sections, metadata={"pages": len(pages)}, original_sha=sha)
