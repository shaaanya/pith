import sys

import pytest

from infoparser.providers.cli_backend import CliBackend
from infoparser.providers.ports import ProviderError

MSG = [{"role": "user", "content": "hello"}]


def test_cli_prompt_via_arg():
    b = CliBackend("c", [sys.executable, "-c", "import sys;print(sys.argv[1])"], prompt_via="arg")
    assert "hello" in b.generate(MSG).text


def test_cli_schema_embedded_in_prompt():
    b = CliBackend("c", [sys.executable, "-c", "import sys;print(sys.stdin.read())"])
    assert '"type": "object"' in b.generate(MSG, json_schema={"type": "object"}).text


def test_cli_nonzero_exit_timeout_and_missing_binary():
    with pytest.raises(ProviderError, match="exit 3"):
        CliBackend("c", [sys.executable, "-c", "import sys;sys.exit(3)"]).generate(MSG)
    with pytest.raises(ProviderError):
        CliBackend("c", [sys.executable, "-c", "import time;time.sleep(5)"], timeout=0.3).generate(MSG)
    with pytest.raises(ProviderError):
        CliBackend("c", ["/no/such/bin"]).generate(MSG)


def test_cli_from_spec_bad_prompt_via():
    with pytest.raises(ValueError):
        CliBackend.from_spec("c", {"command": ["x"], "prompt_via": "pipe"})
