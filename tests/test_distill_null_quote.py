"""`quote: null` on one item must not sink the whole model reply."""
import json

from infoparser.domain.models import SegmentIn
from infoparser.pipeline.distill import distill
from infoparser.providers.heuristic import HeuristicBackend
from infoparser.providers.ports import Capabilities, GenResult
from infoparser.providers.registry import Registry

TEXT = "Rust ownership prevents data races at compile time. Borrowing lets code read."


class _Fake:  # pylint: disable=too-few-public-methods  # a one-method stub
    locality, type, name = "local", "fake", "m"
    capabilities = Capabilities(text=True, context_window=8192)

    def __init__(self, reply):
        self.reply, self.calls = reply, 0

    def generate(self, messages, *, json_schema=None, max_tokens=None):  # pylint: disable=unused-argument
        """One canned reply."""
        self.calls += 1
        return GenResult(json.dumps(self.reply), "fm", self.name)


def test_null_quote_on_one_item_is_tolerated():
    """The reply is used as it is: no repair round trip, the other item stays `stated`."""
    f = _Fake({"summary": "s", "insights": [{"text": "a fact", "quote": None},
                                            {"text": "Rust ownership", "quote": TEXT[:40]}]})
    h = HeuristicBackend()
    h.type = "heuristic"
    reg = Registry({"m": f, "heuristic": h}, {}, {"distill": ["m"]}, False)
    cands, _ = distill(reg, [SegmentIn(0, TEXT, None)], profile="generic", title="t",
                       user_context=None)
    assert f.calls == 1
    assert [(c.title, c.provenance) for c in cands] == [
        ("Summary", "inferred"), ("a fact", "inferred"), ("Rust ownership", "stated")]
