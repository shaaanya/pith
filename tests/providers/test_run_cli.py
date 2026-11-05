"""Direct tests of ports.run_cli: spawn failure, timeout, bad exit, stdin, success."""
import sys

import pytest

from infoparser.providers.ports import ProviderError, run_cli


def py(code):
    """argv running a python snippet."""
    return [sys.executable, "-c", code]


def test_success_returns_completed_process_and_feeds_stdin():
    """stdout is captured and stdin is delivered."""
    p = run_cli("x", py("import sys; print(sys.stdin.read().upper())"), 10, stdin="hello")
    assert p.stdout.strip() == "HELLO"


def test_missing_binary_is_provider_error():
    """A binary that cannot be spawned maps to ProviderError."""
    with pytest.raises(ProviderError, match="^nope: "):
        run_cli("nope", ["/nonexistent/binary-xyz"], 5)


def test_timeout_is_provider_error():
    """A timeout maps to ProviderError."""
    with pytest.raises(ProviderError, match="^slow: .*timed out"):
        run_cli("slow", py("import time; time.sleep(5)"), 0.3)


def test_nonzero_exit_names_code_and_truncates_stderr():
    """Non-zero exit: message carries the code and at most 300 stderr chars."""
    with pytest.raises(ProviderError) as e:
        run_cli("bad", py("import sys; sys.stderr.write('E' * 1000); sys.exit(3)"), 10)
    msg = str(e.value)
    assert msg.startswith("bad: exit 3: ") and msg.count("E") == 300


def test_undecodable_output_is_replaced_not_raised():
    """Invalid UTF-8 output is replaced rather than raising."""
    p = run_cli("x", py("import sys; sys.stdout.buffer.write(b'a\\xffb')"), 10)
    assert p.stdout == "a�b"
