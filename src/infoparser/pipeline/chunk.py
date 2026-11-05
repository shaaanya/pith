import re

from infoparser.providers.ports import TimedText

_BREAK = re.compile(r"\n\s*\n")
_HEADING = re.compile(r"^#{1,6} ", re.M)


def _blocks(text: str) -> list[tuple[int, int, bool]]:
    """(start, end, starts_with_heading) spans split on blank lines and heading lines."""
    cuts = {0, len(text)}
    for m in _BREAK.finditer(text):
        cuts.add(m.end())
    cuts |= {m.start() for m in _HEADING.finditer(text)}
    pts = sorted(cuts)
    out = []
    for a, b in zip(pts, pts[1:]):
        if text[a:b].strip():
            out.append((a, b, bool(_HEADING.match(text, a))))
    return out


def _span(text: str, a: int, b: int) -> tuple[str, str]:
    seg = text[a:b]
    a += len(seg) - len(seg.lstrip())
    b -= len(seg) - len(seg.rstrip())
    return text[a:b], f"char={a}-{b}"


def chunk_text(text: str, *, max_chars=1200, overlap=100) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    cur: list[int] | None = None  # [start, end] of the chunk being packed

    def flush():
        nonlocal cur
        if cur:
            out.append(_span(text, *cur))
        cur = None

    for a, b, heading in _blocks(text):
        if b - a > max_chars:  # oversized block: sliding windows with overlap
            flush()
            step = max(1, max_chars - overlap)
            for s in range(a, b, step):
                out.append(_span(text, s, min(s + max_chars, b)))
                if s + max_chars >= b:
                    break
            continue
        if cur and (heading or len(text[cur[0]:b].strip()) > max_chars):
            flush()
        cur = [cur[0], b] if cur else [a, b]
    flush()
    return out


def _fmt(x: float) -> str:
    return f"{x:g}"


def chunk_timed(items: list[TimedText], max_chars=800) -> list[tuple[str, str]]:
    out, buf = [], []

    def flush():
        if buf:
            out.append((" ".join(t.text for t in buf), f"t={_fmt(buf[0].start)}-{_fmt(buf[-1].end)}"))
            buf.clear()

    for it in items:
        if buf and sum(len(t.text) + 1 for t in buf) + len(it.text) > max_chars:
            flush()
        buf.append(it)
    flush()
    return out
