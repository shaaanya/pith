import json

import pytest

from infoparser.providers.ports import CapabilityError

KINDS = ["heuristic", "openai_compat", "cli"]
MSGS = [{"role": "user", "content": "Rust ownership rules prevent data races at compile time. "
                                    "Borrowing lets code read data without taking ownership of it."}]
SCHEMA = {"type": "object", "properties": {"summary": {"type": "string"}}}


@pytest.mark.parametrize("kind", KINDS)
def test_contract_generate_returns_text_for_every_text_backend(backends, kind):
    b = backends[kind]
    assert b.capabilities.text and b.locality in ("local", "remote")
    r = b.generate(MSGS)
    assert isinstance(r.text, str) and r.text and r.backend == b.name and r.model


@pytest.mark.parametrize("kind", KINDS)
def test_contract_json_schema_output_parses(backends, kind):
    out = json.loads(backends[kind].generate(MSGS, json_schema=SCHEMA).text)
    assert isinstance(out["summary"], str) and isinstance(out["insights"], list)


@pytest.mark.parametrize("kind", KINDS)
def test_contract_embeddings_dimension_consistent(backends, kind):
    b = backends[kind]
    if kind != "openai_compat":
        with pytest.raises(CapabilityError):
            b.embed(["x"])
        return
    r = b.embed(["alpha beta", "gamma", "alpha beta"])
    assert len({len(v) for v in r.vectors}) == 1 and len(r.vectors[0]) == 64
    assert r.vectors[0] == r.vectors[2] and r.model_id == "oa:e"


def test_heuristic_is_deterministic_and_extractive(backends):
    a = backends["heuristic"].generate(MSGS, json_schema=SCHEMA).text
    assert a == backends["heuristic"].generate(MSGS, json_schema=SCHEMA).text
    assert all(i["quote"] in MSGS[0]["content"] for i in json.loads(a)["insights"])
