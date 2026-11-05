"""Extractor for images: OCR, else a vision backend."""
from infoparser.pipeline.extractors.base import (
    Extracted, ExtractCtx, NeedsClarificationError, register)

NO_OCR = "no OCR backend; install tesseract"
_PROMPT = "Transcribe all text visible in this image, then briefly describe it."


@register("image")
def extract(ctx: ExtractCtx) -> Extracted:
    """Read text from the image via the first `ocr` backend, else `describe`."""
    sha = ctx.row["blob_sha256"]
    if not sha:
        raise NeedsClarificationError("image item has no file")
    path = ctx.blobs.path(sha)
    ocr = ctx.registry.first("ocr")
    if ocr is not None:
        text, how = ocr.read(path), "ocr"
    elif (vision := ctx.registry.first("describe")) is not None:
        text, how = vision.describe([path], _PROMPT), "vision"
    else:
        raise NeedsClarificationError(NO_OCR)
    text = (text or "").replace("\x00", "").strip()
    if not text:
        raise NeedsClarificationError("no text found in image", pasteable=True)
    return Extracted(ctx.row["original_filename"] or "Image", None, ctx.row["canonical_url"],
                     "image", text, metadata={"via": how}, original_sha=sha)
