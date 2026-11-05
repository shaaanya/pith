"""In-process OpenAI-wire stub.

Serves /v1/chat/completions, /v1/embeddings, /v1/models and /v1/audio/transcriptions.
"""
import hashlib
import json
import re

from .fake_llm import reply_for
from .json_server import JsonHandler, JsonStub


def hashed_bow(text: str, dim: int = 64) -> list[float]:
    """Hashed bag-of-words vector."""
    v = [0.0] * dim
    for w in re.findall(r"\w+", text.lower()):
        v[int(hashlib.md5(w.encode()).hexdigest(), 16) % dim] += 1.0
    return v


class _H(JsonHandler):
    """Request handler: records requests, answers canned JSON."""

    def do_GET(self):  # pylint: disable=invalid-name  # http.server dispatch name
        """GET /v1/models."""
        if self.path == "/v1/models":
            self._send(200, {"data": [{"id": "stub-model"}]})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):  # pylint: disable=invalid-name  # http.server dispatch name
        """POST chat/embeddings/transcriptions (or the configured failure)."""
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self.server.requests.append((self.path, dict(self.headers), body))
        if self.server.fail_with:
            self._send(self.server.fail_with, {"error": {"message": "boom"}})
            return
        if self.path == "/v1/chat/completions":
            req = json.loads(body)
            prompt = "\n".join(m["content"] for m in req["messages"])
            self._send(200, {"model": req["model"], "choices": [
                {"message": {"role": "assistant", "content": reply_for(prompt)}}]})
            return
        if self.path == "/v1/embeddings":
            req = json.loads(body)
            self._send(200, {"data": [{"index": i, "embedding": hashed_bow(t)}
                                      for i, t in enumerate(req["input"])]})
            return
        if self.path == "/v1/audio/transcriptions":
            self._send(200, {"segments": [{"start": 0.0, "end": 1.5,
                                           "text": " hello world"}]})
            return
        self._send(404, {"error": "not found"})


class OpenAIStub(JsonStub):  # pylint: disable=too-few-public-methods  # context-manager stub
    """Context-managed OpenAI-wire server; `fail_with` makes every POST fail with that status."""

    url_suffix = "/v1"

    def __init__(self, fail_with: int | None = None, chat_reply=None):
        super().__init__(_H, fail_with)
        self.server.chat_reply = chat_reply
