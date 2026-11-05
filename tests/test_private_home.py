"""A home created by any command (not only `init`) is private to the user."""
import stat

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
