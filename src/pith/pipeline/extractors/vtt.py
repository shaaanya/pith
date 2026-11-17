"""WebVTT -> TimedText, collapsing YouTube-style rolling auto-captions."""
import html
import re

from pith.providers.ports import TimedText

_STAMP = r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{3})"
_TIME = re.compile(_STAMP + r"\s*-->\s*" + _STAMP)
_TAG = re.compile(r"<[^>]*>")


def _secs(h, m, s, ms) -> float:
    return int(h or 0) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def parse_vtt(text: str) -> list[TimedText]:
    """A rolling cue repeats the previous cue's last line; only lines not in the previous cue are
    emitted, each with its cue's timing. Inline tags, cue settings and NOTE/STYLE blocks are
    dropped."""
    out: list[TimedText] = []
    prev: list[str] = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").lstrip("﻿")):
        lines = block.split("\n")
        i = next((n for n, ln in enumerate(lines) if _TIME.search(ln)), None)
        if i is None:  # header / NOTE / STYLE / junk
            continue
        m = _TIME.search(lines[i])
        start, end = _secs(*m.group(1, 2, 3, 4)), _secs(*m.group(5, 6, 7, 8))
        cue = []
        for ln in lines[i + 1:]:
            ln = " ".join(html.unescape(_TAG.sub("", ln)).split())
            if ln and (not cue or cue[-1] != ln):
                cue.append(ln)
        for ln in cue:
            if ln not in prev:
                out.append(TimedText(start, end, ln))
        if cue:
            prev = cue
    return out
