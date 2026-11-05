"""Real `ollama run` stdout (captured bytes) and generic terminal/JSON tolerance."""
import sys
from pathlib import Path

import pytest

from infoparser.pipeline.distill import _parse
from infoparser.pipeline.schemas import SCHEMAS, validate
from infoparser.providers.cli_backend import CliBackend, clean_terminal_output

FIX = Path(__file__).parent / "fixtures"
CAPTURES = sorted(FIX.glob("ollama_run_*.txt"))


def _text(path):
    return path.read_bytes().decode("utf-8", errors="replace")


def test_captures_present():
    """Three real captures are checked in."""
    assert len(CAPTURES) == 3


@pytest.mark.parametrize("path", CAPTURES, ids=lambda p: p.name)
def test_real_capture_parses_and_validates(path):
    """Cleaned real output is a schema-valid distillation object (fence, wraps and all)."""
    obj = _parse(clean_terminal_output(_text(path)))
    assert obj is not None and validate(obj, SCHEMAS["article"]) is None
    assert obj["summary"].startswith("Vector search finds nearest neighbours")
    assert "documents." in obj["summary"] and "\x1b" not in obj["summary"]


def test_raw_capture_is_not_parseable_without_cleaning():
    """Evidence for why cleaning is needed: the raw bytes hold escape codes inside strings."""
    assert "\x1b[" in _text(CAPTURES[0])
    obj = _parse(_text(CAPTURES[0]))
    assert obj is None or "\x1b" in obj["summary"]


def test_cli_backend_returns_cleaned_capture():
    """CliBackend.generate cleans stdout of a command that replays a captured byte stream."""
    cmd = [sys.executable, "-c",
           "import sys; sys.stdout.buffer.write(open(sys.argv[1], 'rb').read())", str(CAPTURES[1])]
    res = CliBackend("c", cmd).generate([{"role": "user", "content": "x"}])
    assert "\x1b" not in res.text
    assert _parse(res.text)["topics"] == ["Retrieval Systems", "Embeddings"]


@pytest.mark.parametrize("raw,clean", [
    ("plain text\n", "plain text\n"),
    ("a\x1b[31mred\x1b[0m b", "ared b"),
    ("spin 1\rspin 2\rdone!!", "done!!"),
    ("hello wor\x1b[3D\x1b[Kworld", "hello world"),
    ("\x1b[?2026h\x1b[?25lx\x1b[?25h", "x"),
    ("\x1b]0;title\x07text", "text"),
    ("ab\x08Xc", "aXc"),
    ("keep\r\nline", "keep\nline"),
    ("line1\x1b[2Kline2", "line2"),
])
def test_clean_terminal_output(raw, clean):
    """Cursor moves, erases, CR and escape sequences are rendered as a terminal would."""
    assert clean_terminal_output(raw) == clean


@pytest.mark.parametrize("reply", [
    '```json\n{"summary": "s"}\n```\n\n',
    'Sure! Here you go:\n{"summary": "s"}\nHope that helps {really}.',
    '```\n{"summary": "s"}\n```',
    '{"summary": "s"}',
    'noise { not json } then {"summary": "s"} {"other": 1}',
])
def test_parse_extracts_first_balanced_object(reply):
    """Fences and surrounding prose are tolerated."""
    assert _parse(reply) == {"summary": "s"}


@pytest.mark.parametrize("reply", ["", "no json here", "{broken", '{"a": '])
def test_parse_gives_none_when_no_object(reply):
    """Nothing is invented from text without a JSON object."""
    assert _parse(reply) is None


def test_parse_keeps_object_that_fails_schema_so_validation_decides():
    """Extraction never fixes content: a wrong-shaped object is returned and then rejected."""
    obj = _parse('Here: {"foo": 1}')
    assert obj == {"foo": 1} and validate(obj, SCHEMAS["article"]) is not None
