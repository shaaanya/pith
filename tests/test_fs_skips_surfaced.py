"""fs adapter skips (oversize, escaping symlink) are reported, not silent."""
import logging

from pith.adapters.fs import FsAdapter


def test_fs_skips_are_logged_once_and_files_kept(svc, tmp_path, caplog):
    """Oversize files and escaping symlinks are reported (once each), never lost."""
    drop = tmp_path / "drop"
    drop.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("top secret", encoding="utf-8")
    (drop / "link.txt").symlink_to(secret)
    big = drop / "big.bin"
    big.write_bytes(b"x" * 50)
    svc.cfg.max_fetch_bytes = 10
    fa = FsAdapter(svc.inbox, [drop], stable_polls=1)
    with caplog.at_level(logging.WARNING, logger="pith.adapters.fs"):
        fa.poll()
        fa.poll()
    msgs = [r.getMessage() for r in caplog.records]
    assert sum("big.bin" in m and "max_fetch_bytes" in m for m in msgs) == 1
    assert sum("link.txt" in m and "symlink" in m for m in msgs) == 1
    assert big.exists() and secret.exists()


def test_fixed_file_rewarned_when_oversize_again_and_removed_paths_pruned(svc, tmp_path, caplog):
    """A skip clears once the file is fine or gone, so it re-warns later and does not accumulate."""
    drop = tmp_path / "drop"
    drop.mkdir()
    big = drop / "big.bin"
    big.write_bytes(b"x" * 50)
    svc.cfg.max_fetch_bytes = 10
    fa = FsAdapter(svc.inbox, [drop], stable_polls=99)  # never submits: only skip tracking
    with caplog.at_level(logging.WARNING, logger="pith.adapters.fs"):
        fa.poll()
        big.write_bytes(b"x" * 5)  # fixed
        fa.poll()
        assert big not in fa.skipped
        big.write_bytes(b"x" * 50)  # oversize again
        fa.poll()
        assert sum("big.bin" in r.getMessage() for r in caplog.records) == 2
        big.unlink()
        fa.poll()
    assert not fa.skipped
