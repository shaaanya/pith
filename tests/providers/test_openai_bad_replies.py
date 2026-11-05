"""Odd-but-valid-JSON replies from an OpenAI-wire server become ProviderError, not crashes."""
import pytest
from stubs.json_server import JsonHandler, JsonStub

from infoparser.domain.models import SegmentIn
from infoparser.pipeline.distill import distill
from infoparser.providers.heuristic import HeuristicBackend
from infoparser.providers.openai_compat import OpenAICompatBackend
from infoparser.providers.ports import Capabilities, ProviderError
from infoparser.providers.registry import Registry

MSG = [{"role": "user", "content": "hi"}]


class _H(JsonHandler):
    def do_POST(self):  # pylint: disable=invalid-name  # http.server dispatch name
        """Answer with the stub's canned body."""
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self._send(200, self.server.canned)


def _stub(canned):
    s = JsonStub(_H)
    s.server.canned = canned
    return s


REFUSAL = {"choices": [{"message": {"role": "assistant", "content": None, "refusal": "no"}}]}
PARTS = {"choices": [{"message": {"content": [{"type": "text", "text": "x"}]}}]}
MISSING = {"choices": [{"message": {"role": "assistant"}}]}


@pytest.mark.parametrize("canned", [REFUSAL, PARTS, MISSING])
def test_non_string_content_is_a_provider_error(canned):
    """content: null (a refusal), a parts list or a missing content must not leak None."""
    with _stub(canned) as s:
        with pytest.raises(ProviderError):
            OpenAICompatBackend("oa", s.base_url, "m").generate(MSG)


def test_distill_falls_back_to_the_heuristic_on_a_null_content_reply():
    """distill keeps going to the next backend instead of failing the item."""
    with _stub(REFUSAL) as s:
        oa = OpenAICompatBackend("oa", s.base_url, "m")
        oa.type = "openai_compat"
        h = HeuristicBackend()
        h.type = "heuristic"
        reg = Registry({"oa": oa, "heuristic": h}, {}, {"distill": ["oa"]}, False)
        text = "Rust ownership prevents data races at compile time. Borrowing lets code read."
        cands, by = distill(reg, [SegmentIn(0, text, None)], profile="generic", title="t",
                            user_context=None)
    assert cands and by.startswith("heuristic")


def test_negative_rerank_index_is_rejected():
    """index -1 must not score the last document."""
    canned = {"results": [{"index": -1, "relevance_score": 0.9}]}
    with _stub(canned) as s:
        b = OpenAICompatBackend("oa", s.base_url, "m", capabilities=Capabilities(rerank=True))
        with pytest.raises(ProviderError):
            b.rerank("q", ["a", "b"])
