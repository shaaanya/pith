import pytest

from infoparser.providers.registry import Registry

H = {"type": "heuristic"}


def test_registry_fallback_order(make_cfg):
    cfg = make_cfg({"a": {"type": "cli", "command": ["x"]}, "b": {"type": "cli", "command": ["y"]}, "heuristic": H},
                   {"distill": ["b", "a"]})
    r = Registry.from_config(cfg)
    assert [x.name for x in r.chain("distill")] == ["b", "a", "heuristic"]
    assert r.first("distill").name == "b"
    assert r.first("embed") is None


def test_registry_heuristic_implicit_last(make_cfg):
    r = Registry.from_config(make_cfg({"a": {"type": "cli", "command": ["x"]}}, {"distill": ["a"]}))
    assert [x.name for x in r.chain("distill")] == ["a", "heuristic"]


def test_registry_blocks_remote_by_default(make_cfg):
    be = {"far": {"type": "cli", "command": ["x"], "locality": "remote"}}
    tasks = {"distill": ["far"]}
    assert [x.name for x in Registry.from_config(make_cfg(be, tasks)).chain("distill")] == ["heuristic"]
    assert [x.name for x in Registry.from_config(make_cfg(be, tasks, True)).chain("distill")] == ["far", "heuristic"]


def test_registry_unknown_type_raises(make_cfg):
    with pytest.raises(ValueError, match="unknown type"):
        Registry.from_config(make_cfg({"z": {"type": "nope"}}))


def test_registry_unknown_task_ref_raises(make_cfg):
    with pytest.raises(ValueError, match="unknown backend"):
        Registry.from_config(make_cfg({"a": H}, {"distill": ["ghost"]}))


def test_registry_unshipped_type_errors_only_when_configured(make_cfg):
    Registry.from_config(make_cfg({"a": H}))  # tesseract etc. never imported
    with pytest.raises(ValueError, match="unavailable"):
        Registry.from_config(make_cfg({"t": {"type": "tesseract"}}))


def test_registry_name_model_override_and_describe(make_cfg, stub):
    be = {"oa": {"type": "openai_compat", "base_url": stub.base_url, "model": "m1", "embed_model": "e"}}
    r = Registry.from_config(make_cfg(be, {"distill": ["oa:m2"]}))
    assert r.first("distill").model == "m2"
    d = {x["name"]: x for x in r.describe()}
    assert d["oa"]["type"] == "openai_compat" and d["oa"]["capabilities"]["embeddings"]
    assert "embed" in d["oa"]["tasks"] and "distill" in d["heuristic"]["tasks"]
