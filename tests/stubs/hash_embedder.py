"""Deterministic hashing embedder for tests."""
import hashlib
import re

from infoparser.providers.ports import Capabilities, EmbedResult


class HashEmbedder:  # pylint: disable=too-few-public-methods  # the Embedder port has one method
    """Bag-of-words hashing embedder implementing the Embedder port (no model, fixed dim)."""

    locality = "local"
    capabilities = Capabilities(embeddings=True)

    def __init__(self, model_id="test-embed-1", dim=64):
        self.name, self.model_id, self.dim = "hash", model_id, dim

    def embed(self, texts):
        """One hashed bag-of-words vector per text."""
        out = []
        for t in texts:
            v = [0.0] * self.dim
            for w in re.findall(r"\w+", t.lower()):
                v[int(hashlib.md5((self.model_id + w).encode()).hexdigest(), 16) % self.dim] += 1.0
            out.append(v)
        return EmbedResult(self.model_id, out)
