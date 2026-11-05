"""Deterministic, offline, extractive backend. Always the last text fallback.

Spec keys (config [backends.<name>]): type = "heuristic"  (no other keys).
generate(json_schema=...) returns JSON {"summary": str, "insights": [{"text", "quote"}]}
where insights are the top sentences by summed term frequency (quote == text, so
evidence checks against the source pass by construction).
"""
import json
import re
from collections import Counter

from .ports import Capabilities, CapabilityError, GenResult

_SENT = re.compile(r"(?<=[.!?])\s+|\n+")
_WORD = re.compile(r"\w+")


class HeuristicBackend:
    """Extractive summariser; the always-available text backend."""

    locality = "local"
    capabilities = Capabilities(text=True, json_mode=True, context_window=1_000_000)

    def __init__(self, name: str = "heuristic", top_n: int = 5):
        self.name, self.top_n = name, top_n

    @classmethod
    def from_spec(cls, name: str, spec: dict) -> "HeuristicBackend":  # pylint: disable=unused-argument
        """Build from config; the spec has no keys (signature fixed by the registry)."""
        return cls(name)

    def generate(self, messages, *, json_schema=None,
                 max_tokens=None) -> GenResult:  # pylint: disable=unused-argument
        """Pick the top sentences by term frequency (max_tokens is part of the port, unused)."""
        text = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        sents = [s.strip() for s in _SENT.split(text) if len(s.strip()) > 20]
        tf = Counter(w for w in _WORD.findall(text.lower()) if len(w) > 3)
        def score(s: str) -> float:
            return sum(tf[w] for w in _WORD.findall(s.lower())) / (1 + len(s) / 200)

        top = sorted(range(len(sents)), key=lambda i: (-score(sents[i]), i))[: self.top_n]
        picked = [sents[i] for i in sorted(top)]  # keep document order
        if json_schema is None:
            out = " ".join(picked)
        else:
            out = json.dumps({"summary": picked[0] if picked else text[:200].strip(),
                              "insights": [{"text": s, "quote": s} for s in picked]})
        return GenResult(out, "heuristic", self.name)

    def embed(self, texts):
        """Not supported: raises CapabilityError."""
        raise CapabilityError(f"{self.name}: embeddings not supported")
