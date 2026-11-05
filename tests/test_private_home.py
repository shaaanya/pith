"""A home created by any command (not only `init`) is private to the user."""
import stat

from infoparser import locks, run_all
from infoparser.cli import main
from infoparser.config import load_config
from infoparser.services import build


def test_first_use_creates_a_private_home_and_database(tmp_path):
    """0700 home, 0600 database, without running `infoparser init` first."""
    home = tmp_path / "new" / "home"
    build(load_config(env={"INFOPARSER_HOME": str(home)}))
    assert stat.S_IMODE(home.stat().st_mode) == 0o700
    assert stat.S_IMODE((home / "infoparser.db").stat().st_mode) == 0o600


def test_existing_home_permissions_are_left_alone(tmp_path):
    """Only a home we create is locked down; a directory the user already owns keeps its mode."""
    home = tmp_path / "home"
    home.mkdir(mode=0o755)
    home.chmod(0o755)
    build(load_config(env={"INFOPARSER_HOME": str(home)}))
    assert stat.S_IMODE(home.stat().st_mode) == 0o755


def test_first_command_that_takes_the_in_use_lock_still_creates_a_private_home(tmp_path):
    """submit/worker/... lock the home before building services; the lock must not create 0755."""
    main(["--home", str(tmp_path / "a"), "submit", "hello"])
    assert stat.S_IMODE((tmp_path / "a").stat().st_mode) == 0o700
    with locks.in_use(tmp_path / "b"):
        pass
    assert stat.S_IMODE((tmp_path / "b").stat().st_mode) == 0o700
    lock = run_all._Lock(tmp_path / "c")  # pylint: disable=protected-access
    lock.release()
    assert stat.S_IMODE((tmp_path / "c").stat().st_mode) == 0o700
