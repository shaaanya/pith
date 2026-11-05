from pathlib import Path

from infoparser.config import load_config
from infoparser.ids import new_id, utcnow


def test_load_config_env_overrides_file(tmp_path):
    cfg_file = tmp_path / "c.toml"
    cfg_file.write_text(
        f'home = "{tmp_path / "filehome"}"\n[privacy]\nallow_remote = true\n'
        '[tasks]\ndistill = ["a", "b:m"]\n[backends.a]\ntype = "heuristic"\n'
    )
    cfg = load_config(cfg_file, env={"INFOPARSER_HOME": str(tmp_path / "envhome")})
    assert cfg.home == tmp_path / "envhome"
    assert cfg.db_path == cfg.home / "infoparser.db"
    assert cfg.allow_remote is True
    assert cfg.tasks == {"distill": ["a", "b:m"]}
    assert cfg.backends["a"]["type"] == "heuristic"
    # INFOPARSER_CONFIG env selects the file when no path given
    cfg2 = load_config(env={"INFOPARSER_CONFIG": str(cfg_file)})
    assert cfg2.home == tmp_path / "filehome"


def test_load_config_defaults_home_under_userhome(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = load_config(env={})
    assert cfg.home == Path(tmp_path) / "InfoParser"
    assert cfg.allow_remote is False
    assert (cfg.max_attempts, cfg.lease_seconds, cfg.max_fetch_bytes) == (5, 300, 50_000_000)
    assert cfg.blobs_dir == cfg.home / "blobs" and cfg.vault_dir == cfg.home / "vault"
    assert cfg.backends == {} and cfg.tasks == {}


def test_ids():
    a, b = new_id(), new_id()
    assert len(a) == 26 and a != b
    import time
    time.sleep(0.003)
    assert new_id() > a
    assert len(utcnow()) == 20 and utcnow().endswith("Z")
