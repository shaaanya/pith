"""Local Anthropic Messages API fixture server (/v1/messages)."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .fake_llm import reply_for


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

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self.server.requests.append((self.path, {k.lower(): v for k, v in self.headers.items()}, body))
        if self.server.fail_with:
            return self._send(self.server.fail_with, {"type": "error", "error": {
                "type": "overloaded_error", "message": "server says no"}})
        if self.path != "/v1/messages":
            return self._send(404, {})
        req = json.loads(body)
        prompt = "\n".join(m["content"] if isinstance(m["content"], str) else m["content"][0]["text"]
                           for m in req["messages"])
        self._send(200, {"id": "msg_1", "type": "message", "role": "assistant", "model": req["model"],
                         "content": [{"type": "thinking", "thinking": "x"},
                                     {"type": "text", "text": reply_for(prompt)}],
                         "stop_reason": "end_turn"})


class AnthropicStub:
    def __init__(self, fail_with=None):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _H)
        self.server.requests, self.server.fail_with = [], fail_with
        self.requests = self.server.requests

    @property
    def base_url(self):
        return f"http://127.0.0.1:{self.server.server_port}"

    def __enter__(self):
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()
