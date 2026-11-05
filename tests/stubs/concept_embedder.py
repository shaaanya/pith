"""Deterministic concept embedder: words in the same concept group share one strong dimension (so
paraphrases with no word overlap still match); every other word hashes into a few weak noise dims."""
import hashlib
import json
import re
from pathlib import Path

from infoparser.providers.ports import Capabilities, EmbedResult

GROUPS = json.loads((Path(__file__).parent.parent / "fixtures" / "concepts.json").read_text())
WORD2G = {w: i for i, ws in enumerate(GROUPS.values()) for w in ws}
NOISE = 16


class ConceptEmbedder:
    locality = "local"
    capabilities = Capabilities(embeddings=True)

    def __init__(self, model_id="concept-1", name="concept"):
        self.name, self.model_id = name, model_id

    def embed(self, texts):
        out = []
        for t in texts:
            v = [0.0] * (len(GROUPS) + NOISE)
            for w in re.findall(r"\w+", t.lower()):
                if w in WORD2G:
                    v[WORD2G[w]] += 3.0
                else:
                    v[len(GROUPS) + int(hashlib.md5(w.encode()).hexdigest(), 16) % NOISE] += 0.3
            out.append(v)
        return EmbedResult(self.model_id, out)
