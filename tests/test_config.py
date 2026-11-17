"""Config loading and ids."""
import time
from pathlib import Path

from pith.config import load_config
from pith.ids import new_id, utcnow


def test_load_config_env_overrides_file(tmp_path):
    """Env overrides the file; PITH_CONFIG selects the file."""
    cfg_file = tmp_path / "c.toml"
    cfg_file.write_text(
        f'home = "{tmp_path / "filehome"}"\n[privacy]\nallow_remote = true\n'
        '[tasks]\ndistill = ["a", "b:m"]\n[backends.a]\ntype = "heuristic"\n'
    )
    cfg = load_config(cfg_file, env={"PITH_HOME": str(tmp_path / "envhome")})
    assert cfg.home == tmp_path / "envhome"
    assert cfg.db_path == cfg.home / "infoparser.db"
    assert cfg.allow_remote is True
    assert cfg.tasks == {"distill": ["a", "b:m"]}
    assert cfg.backends["a"]["type"] == "heuristic"
    # PITH_CONFIG env selects the file when no path given
    cfg2 = load_config(env={"PITH_CONFIG": str(cfg_file)})
    assert cfg2.home == tmp_path / "filehome"


def test_load_config_defaults_home_under_userhome(monkeypatch, tmp_path):
    """Defaults: home under the user home, local-only, sane limits."""
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = load_config(env={})
    assert cfg.home == Path(tmp_path) / "Pith"
    assert cfg.allow_remote is False
    assert (cfg.max_attempts, cfg.lease_seconds, cfg.max_fetch_bytes) == (5, 300, 50_000_000)
    assert cfg.blobs_dir == cfg.home / "blobs" and cfg.vault_dir == cfg.home / "vault"
    assert not cfg.backends and not cfg.tasks


def test_ids():
    """Ids are 26 chars and time-ordered; timestamps are UTC Z."""
    a, b = new_id(), new_id()
    assert len(a) == 26 and a != b
    time.sleep(0.003)
    assert new_id() > a
    assert len(utcnow()) == 20 and utcnow().endswith("Z")


def test_old_infoparser_env_names_still_work_and_new_ones_win(tmp_path):
    from pith.config import load_config
    assert load_config(env={"INFOPARSER_HOME": str(tmp_path)}).home == tmp_path
    assert load_config(env={"INFOPARSER_HOME": "/old", "PITH_HOME": str(tmp_path)}).home == tmp_path
