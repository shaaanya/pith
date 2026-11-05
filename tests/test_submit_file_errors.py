"""`submit --file` with an unusable path is one clean error line."""
import pytest

from infoparser.cli import main


@pytest.mark.parametrize("make", [lambda tmp: tmp / "nope.pdf", lambda tmp: tmp])
def test_submit_file_missing_or_directory(tmp_path, make):
    """FileNotFoundError / IsADirectoryError must not escape as a traceback."""
    with pytest.raises(SystemExit) as e:
        main(["--home", str(tmp_path / "h"), "submit", "--file", str(make(tmp_path))])
    assert str(e.value).startswith("error: ")


def test_submit_without_input_has_the_error_prefix(tmp_path):
    """Consistent `error:` prefix."""
    with pytest.raises(SystemExit) as e:
        main(["--home", str(tmp_path / "h"), "submit"])
    assert str(e.value).startswith("error: ")
