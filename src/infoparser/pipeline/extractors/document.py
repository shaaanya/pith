"""docx / pptx / xlsx via stdlib zipfile + ElementTree."""
from __future__ import annotations

import re
import zipfile
from xml.etree import ElementTree as ET

from infoparser.pipeline.extractors.base import (
    Extracted, ExtractCtx, NeedsClarificationError, register)

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


class _Budget:  # pylint: disable=too-few-public-methods  # tiny stateful guard
    """Caps total decompressed bytes across members (zip-bomb guard)."""

    def __init__(self, zf: zipfile.ZipFile, limit: int):
        self.zf, self.left, self.limit = zf, limit, limit

    def xml(self, name: str) -> ET.Element:
        """Parse member `name`, charging its size against the budget."""
        with self.zf.open(name) as f:
            data = f.read(self.left + 1)
        self.left -= len(data)
        if self.left < 0:
            raise NeedsClarificationError(f"document expands beyond max_fetch_bytes ({self.limit})")
        return ET.fromstring(data)


def _num(name: str) -> int:
    return int(re.search(r"(\d+)\.xml$", name).group(1))


def _docx(b: _Budget) -> list[tuple[str, str]]:
    lines = []
    for p in b.xml("word/document.xml").iter(W + "p"):
        text = "".join(t.text or "" for t in p.iter(W + "t")).strip()
        if not text:
            continue
        st = p.find(f"{W}pPr/{W}pStyle")
        m = (re.fullmatch(r"(?:Heading|heading)(\d)", st.get(W + "val", ""))
             if st is not None else None)
        lines.append(f"{'#' * int(m.group(1))} {text}" if m else text)
    return [("document", "\n\n".join(lines))]


def _pptx(b: _Budget) -> list[tuple[str, str]]:
    names = sorted((n for n in b.zf.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
                   key=_num)
    out = []
    for n in names:
        paras = ["".join(t.text or "" for t in p.iter(A + "t")).strip()
                 for p in b.xml(n).iter(A + "p")]
        out.append((f"slide={_num(n)}", "\n\n".join(p for p in paras if p)))
    return out


def _xlsx(b: _Budget) -> list[tuple[str, str]]:
    shared = []
    if "xl/sharedStrings.xml" in b.zf.namelist():
        shared = ["".join(t.text or "" for t in si.iter(S + "t"))
                  for si in b.xml("xl/sharedStrings.xml").iter(S + "si")]
    names = sorted((n for n in b.zf.namelist()
                    if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n)), key=_num)
    out = []
    for n in names:
        rows = []
        for row in b.xml(n).iter(S + "row"):
            cells = []
            for c in row.iter(S + "c"):
                v = c.find(S + "v")
                if c.get("t") == "s" and v is not None:
                    idx = int(v.text) if v.text and v.text.strip().isdecimal() else len(shared)
                    cells.append(shared[idx] if idx < len(shared) else "")
                elif c.get("t") == "inlineStr":
                    cells.append("".join(t.text or "" for t in c.iter(S + "t")))
                else:
                    cells.append(v.text if v is not None and v.text else "")
            if any(cells):
                rows.append("\t".join(cells))
        out.append((f"sheet={_num(n)}", "\n".join(rows)))
    return out


@register("document")
def extract(ctx: ExtractCtx) -> Extracted:
    """Extract docx/pptx/xlsx text as located sections (size- and expansion-capped)."""
    sha = ctx.row["blob_sha256"]
    if not sha:
        raise NeedsClarificationError("document item has no file")
    path = ctx.blobs.path(sha)
    if path.stat().st_size > ctx.cfg.max_fetch_bytes:
        raise NeedsClarificationError(
            f"file larger than max_fetch_bytes ({ctx.cfg.max_fetch_bytes})")
    try:
        zf = zipfile.ZipFile(path)
    except zipfile.BadZipFile as e:
        raise RuntimeError(f"not a valid office document: {e}") from e
    with zf:
        names = set(zf.namelist())
        b = _Budget(zf, ctx.cfg.max_fetch_bytes)
        if "word/document.xml" in names:
            sections = _docx(b)
        elif "ppt/presentation.xml" in names:
            sections = _pptx(b)
        elif "xl/workbook.xml" in names:
            sections = _xlsx(b)
        else:
            raise NeedsClarificationError(
                "unsupported document format (supported: docx, pptx, xlsx)")
    sections = [(loc, t) for loc, t in sections if t.strip()]
    if not sections:
        raise NeedsClarificationError("empty document: nothing to extract", pasteable=True)
    return Extracted(ctx.row["original_filename"] or "Untitled document", None,
                     ctx.row["canonical_url"], "document", "\n\n".join(t for _, t in sections),
                     sections=sections, original_sha=sha)
