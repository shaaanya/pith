import json

import pytest

from infoparser.providers.anthropic import AnthropicBackend
from infoparser.providers.ports import CapabilityError, ProviderError, RemoteBlocked
from infoparser.providers.registry import Registry
from stubs.anthropic_stub import AnthropicStub

MSGS = [{"role": "system", "content": "be terse"}, {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "yo"}, {"role": "user", "content": "again"}]


@pytest.fixture
def key(monkeypatch):
    monkeypatch.setenv("IP_ANTH_KEY", "sk-secret-123")


def test_anthropic_request_shape_and_response_parse(key):
    with AnthropicStub() as s:
        b = AnthropicBackend("a", "some-model", "IP_ANTH_KEY", base_url=s.base_url, max_tokens=321)
        assert b.locality == "remote" and b.capabilities.text
        r = b.generate(MSGS, json_schema={"type": "object"})
        path, h, body = s.requests[-1]
    req = json.loads(body)
    assert path == "/v1/messages"
    assert h["x-api-key"] == "sk-secret-123" and h["anthropic-version"] == "2023-06-01"
    assert h["content-type"] == "application/json"
    assert req["model"] == "some-model" and req["max_tokens"] == 321
    assert req["system"].startswith("be terse") and "JSON" in req["system"] and '"type": "object"' in req["system"]
    assert [m["role"] for m in req["messages"]] == ["user", "assistant", "user"]
    assert r.text.startswith("{") and r.model == "some-model" and r.backend == "a"  # text block only


def test_anthropic_max_tokens_arg_overrides_and_version_configurable(key):
    with AnthropicStub() as s:
        b = AnthropicBackend("a", "m", "IP_ANTH_KEY", base_url=s.base_url, anthropic_version="2099-01-01")
        b.generate(MSGS[1:2], max_tokens=7)
        assert json.loads(s.requests[-1][2])["max_tokens"] == 7
        assert s.requests[-1][1]["anthropic-version"] == "2099-01-01"
        assert "system" not in json.loads(s.requests[-1][2])


@pytest.mark.parametrize("code", [401, 429, 500, 529])
def test_anthropic_http_errors_map_without_leaking_key(key, code):
    with AnthropicStub(fail_with=code) as s:
        b = AnthropicBackend("a", "m", "IP_ANTH_KEY", base_url=s.base_url)
        with pytest.raises(ProviderError, match=f"HTTP {code}.*server says no") as e:
            b.generate(MSGS[1:2])
    assert "sk-secret-123" not in str(e.value)


def test_anthropic_missing_key_names_env_var_only(monkeypatch):
    monkeypatch.delenv("IP_ANTH_KEY", raising=False)
    with pytest.raises(ProviderError, match="IP_ANTH_KEY"):
        AnthropicBackend("a", "m", "IP_ANTH_KEY", base_url="http://127.0.0.1:1").generate(MSGS[1:2])


def test_anthropic_embed_unsupported():
    with pytest.raises(CapabilityError):
        AnthropicBackend("a", "m", "K").embed(["x"])


def test_anthropic_blocked_when_remote_disallowed(make_cfg):
    be = {"cloud": {"type": "anthropic", "model": "REPLACE_WITH_MODEL", "api_key_env": "K"}}
    tasks = {"distill": ["cloud"]}
    r = Registry.from_config(make_cfg(be, tasks))
    assert [b.name for b in r.chain("distill")] == ["heuristic"]
    assert r.skipped[0]["name"] == "cloud"
    with pytest.raises(RemoteBlocked):
        r.get("cloud")
    assert Registry.from_config(make_cfg(be, tasks, True)).get("cloud").type == "anthropic"
    assert {d["name"] for d in r.describe()} >= {"cloud"}
