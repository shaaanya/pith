"""`infoparser clarify ID TEXT...` is the CLI twin of the dashboard clarification box."""

import pytest
from stubs.http_fixture_server import FIXTURES, FixtureServer, Route

from infoparser import cli
from infoparser.pipeline import runner
from infoparser.worker import NeedsClarification, Processed


def test_clarify_requeues_and_the_text_becomes_the_content(svc, capsys):
    """A login wall asks for text; the CLI clarification supplies it and the item completes."""
    with FixtureServer({"/w": Route(FIXTURES / "login_wall.html")}) as srv:
        iid = svc.inbox.submit(adapter="t", text=srv.base + "/w").id
        assert isinstance(runner.process(svc, iid), NeedsClarification)
        home = ["--home", str(svc.cfg.home)]
        cli.main([*home, "clarify", iid, "Quokkas", "live", "on", "Rottnest", "Island."])
        assert "requeued" in capsys.readouterr().out
        assert isinstance(runner.process(svc, iid), Processed)
    row = svc.conn.execute("SELECT text FROM segments").fetchone()
    assert "Rottnest" in row["text"]


def test_clarify_rejects_unknown_ids_and_blank_text(svc):
    """Both fail with a one-line error, not a traceback."""
    home = ["--home", str(svc.cfg.home)]
    with pytest.raises(SystemExit, match="unknown id"):
        cli.main([*home, "clarify", "nope", "text"])
    iid = svc.inbox.submit(adapter="t", text="a note").id
    with pytest.raises(SystemExit, match="empty"):
        cli.main([*home, "clarify", iid, " "])
