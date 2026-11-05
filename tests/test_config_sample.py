"""config.sample.toml parses, loads, and builds a registry (placeholders are never contacted)."""
from pathlib import Path

from infoparser.config import load_config
from infoparser.providers.registry import Registry

SAMPLE = Path(__file__).parent.parent / "config.sample.toml"


def test_sample_loads_and_builds(tmp_path):
    """The sample is a valid config: defaults are safe and the routes resolve."""
    cfg = load_config(SAMPLE, env={"INFOPARSER_HOME": str(tmp_path / "home")})
    assert cfg.allow_remote is False
    assert cfg.http_bind == "127.0.0.1"
    assert set(cfg.backends) >= {"local", "heuristic"}
    reg = Registry.from_config(cfg)
    assert [b.type for b in reg.chain("distill")] == ["openai_compat", "heuristic"]
    assert not any(b.locality == "remote" for b in reg.chain("distill"))
