"""One-shot commands that write take the shared in-use lock, so a running restore excludes them."""
import pytest

from pith import locks
from pith.cli import main

COMMANDS = [("submit", "hello"), ("retry", "x"), ("clarify", "x", "text"), ("reindex",),
            ("export",), ("digest",), ("import-telegram", "nowhere")]


@pytest.mark.parametrize("argv", COMMANDS, ids=lambda a: a[0])
def test_one_shot_command_refuses_while_a_restore_holds_the_home(tmp_path, argv):
    """restore (exclusive in-use lock) is running: the command must not write into the old DB."""
    home = tmp_path / "h"
    main(["--home", str(home), "submit", "seed"])
    with locks.restore_guard(home, home / "infoparser.db"):
        with pytest.raises(SystemExit) as e:
            main(["--home", str(home), *argv])
    assert "restore is running" in str(e.value)
