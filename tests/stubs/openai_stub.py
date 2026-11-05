"""In-process OpenAI-wire stub: /v1/chat/completions, /v1/embeddings, /v1/models, /v1/audio/transcriptions."""
import hashlib
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .fake_llm import reply_for


def hashed_bow(text: str, dim: int = 64) -> list[float]:
    v = [0.0] * dim
    for w in re.findall(r"\w+", text.lower()):
        v[int(hashlib.md5(w.encode()).hexdigest(), 16) % dim] += 1.0
    return v


class _H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        raw = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == "/v1/models":
            return self._send(200, {"data": [{"id": "stub-model"}]})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self.server.requests.append((self.path, dict(self.headers), body))
        if self.server.fail_with:
            return self._send(self.server.fail_with, {"error": {"message": "boom"}})
        if self.path == "/v1/chat/completions":
            req = json.loads(body)
            prompt = "\n".join(m["content"] for m in req["messages"])
            return self._send(200, {"model": req["model"], "choices": [
                {"message": {"role": "assistant", "content": reply_for(prompt)}}]})
        if self.path == "/v1/embeddings":
            req = json.loads(body)
            return self._send(200, {"data": [{"index": i, "embedding": hashed_bow(t)}
                                             for i, t in enumerate(req["input"])]})
        if self.path == "/v1/audio/transcriptions":
            return self._send(200, {"segments": [{"start": 0.0, "end": 1.5, "text": " hello world"}]})
        self._send(404, {"error": "not found"})


class OpenAIStub:
    def __init__(self, fail_with: int | None = None):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _H)
        self.server.requests, self.server.fail_with = [], fail_with
        self.requests = self.server.requests

    @property
    def base_url(self):
        return f"http://127.0.0.1:{self.server.server_port}/v1"

    def __enter__(self):
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()
