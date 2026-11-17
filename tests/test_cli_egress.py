"""`reindex` and `search` tell the user when text went to a remote backend (like `ask` does)."""
import pytest
from stubs.openai_stub import OpenAIStub

from pith.cli import main

NOTE = "Retrieval augmented generation combines search with generation."


@pytest.fixture(name="remote_cli")
def _remote_cli(tmp_path):
    """A CLI runner whose only embed backend is a 'remote' openai_compat stub."""
    with OpenAIStub() as stub:
        conf = tmp_path / "c.toml"
        conf.write_text(
            "[privacy]\nallow_remote = true\n"
            f'[backends.r]\ntype = "openai_compat"\nbase_url = "{stub.base_url}"\nmodel = "m"\n'
            'embed_model = "e"\nlocality = "remote"\n[tasks]\nembed = ["r"]\n', encoding="utf-8")

        def run(*argv):
            main(["--home", str(tmp_path / "h"), "--config", str(conf), *argv])
        run("submit", NOTE)
        run("worker", "--once")
        yield run


def test_reindex_reports_remote_egress(remote_cli, capsys):
    """The largest egress an install can make must not be silent."""
    capsys.readouterr()
    remote_cli("reindex")
    err = capsys.readouterr().err
    assert "egress:" in err and "r" in err.split("egress:")[1] and "bytes" in err


def test_search_prints_its_egress_line(remote_cli, capsys):
    """The query text went to the remote embedder; docs promise a stderr line."""
    capsys.readouterr()
    remote_cli("search", "retrieval")
    assert "egress: text sent to remote backend(s): r" in capsys.readouterr().err
