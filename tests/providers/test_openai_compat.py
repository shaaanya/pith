import json

import pytest

from infoparser.providers.openai_compat import OpenAICompatBackend
from infoparser.providers.ports import Capabilities, CapabilityError, ProviderError
from stubs.openai_stub import OpenAIStub

MSG = [{"role": "user", "content": "hi"}]
SCHEMA = {"type": "object"}


def _body(stub):
    return json.loads(stub.requests[-1][2])


def test_openai_http_error_maps_to_provider_error():
    with OpenAIStub(fail_with=500) as s:
        with pytest.raises(ProviderError, match="HTTP 500"):
            OpenAICompatBackend("oa", s.base_url, "m").generate(MSG)


def test_openai_connection_refused_maps_to_provider_error():
    with OpenAIStub() as s:
        url = s.base_url
    with pytest.raises(ProviderError):
        OpenAICompatBackend("oa", url, "m", timeout=2).generate(MSG)


def test_openai_json_mode_uses_response_format_else_prompt(stub):
    OpenAICompatBackend("oa", stub.base_url, "m", capabilities=Capabilities(json_mode=True)).generate(MSG, json_schema=SCHEMA)
    assert "response_format" in _body(stub)
    OpenAICompatBackend("oa", stub.base_url, "m").generate(MSG, json_schema=SCHEMA)
    b = _body(stub)
    assert "response_format" not in b and "JSON schema" in b["messages"][-1]["content"]


def test_openai_api_key_from_env(stub, monkeypatch):
    b = OpenAICompatBackend("oa", stub.base_url, "m", api_key_env="IP_TEST_KEY")
    with pytest.raises(ProviderError, match="IP_TEST_KEY"):
        b.generate(MSG)
    monkeypatch.setenv("IP_TEST_KEY", "sekret")
    b.generate(MSG)
    assert stub.requests[-1][1]["Authorization"] == "Bearer sekret"


def test_openai_embed_requires_embed_model(stub):
    with pytest.raises(CapabilityError):
        OpenAICompatBackend("oa", stub.base_url, "m").embed(["x"])


def test_openai_transcribe(stub, tmp_path):
    f = tmp_path / "a.wav"
    f.write_bytes(b"RIFF")
    b = OpenAICompatBackend.from_spec("oa", {"base_url": stub.base_url, "model": "m", "capabilities": ["transcribe"]})
    segs = b.transcribe(f, "en")
    assert (segs[0].start, segs[0].end, segs[0].text) == (0.0, 1.5, "hello world")
    with pytest.raises(CapabilityError):
        OpenAICompatBackend("oa", stub.base_url, "m").transcribe(f)
