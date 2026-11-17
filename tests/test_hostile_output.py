"""Hostile model/CLI output is bounded in time and never raises past the provider boundary."""
import json
import time

import pytest

from pith.pipeline.distill import _parse
from pith.providers.cli_backend import clean_terminal_output

LIMIT = 1.0  # seconds; generous (measured cost before the fix: 3 s to 37 s)

HOSTILE = [
    ("open-braces-100k", "{" * 100_000),
    ("open-braces-2mb", "{" * 2_000_000),
    ("brace-quote-junk-2mb", '{"a": ' * 300_000),
    ("junk-300kb", "{x " * 100_000),
    ("whitespace-2mb", "{" + " " * 2_000_000),
    ("fence-whitespace-2mb", "```json" + " " * 2_000_000),
]


@pytest.mark.parametrize("name,text", HOSTILE, ids=[h[0] for h in HOSTILE])
def test_parse_is_bounded(name, text):
    """_parse returns (None or an object) quickly on hostile input."""
    del name
    start = time.perf_counter()
    _parse(text)
    assert time.perf_counter() - start < LIMIT


def test_valid_objects_still_parse():
    """Normal shapes are unchanged: bare, fenced, inside prose, after junk braces."""
    obj = {"summary": "s", "insights": [{"text": "t", "quote": "q"}]}
    body = json.dumps(obj)
    assert _parse(body) == obj
    assert _parse(f"```json\n{body}\n```") == obj
    assert _parse(f"Sure! {{not json}} here: {body} done") == obj
    assert _parse("{" * 50 + body) == obj


def test_valid_object_after_moderate_prefix():
    """An object preceded by 100 KB of prose still parses (cap is 256 KB)."""
    body = json.dumps({"summary": "s"})
    assert _parse("x" * 100_000 + body) == {"summary": "s"}


def test_oversize_csi_parameter_never_raises():
    """A 5000-digit CSI parameter is ignored instead of raising ValueError."""
    out = clean_terminal_output("ab\x1b[" + "9" * 5000 + "Dcd")
    assert out.startswith("a") and out.endswith("cd")  # oversize parameter = default step of 1
    clean_terminal_output("x\x1b[" + "9" * 5000 + "C")
    clean_terminal_output("x\x1b[" + "9" * 5000 + "G")


def test_normal_csi_unchanged():
    """Cursor-left still rewrites, so legitimate sequences keep working."""
    assert clean_terminal_output("abc\x1b[2Dx") == "axc"
