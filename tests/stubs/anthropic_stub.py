"""Local Anthropic Messages API fixture server (/v1/messages)."""
import json

from .fake_llm import reply_for
from .json_server import JsonHandler, JsonStub


class _H(JsonHandler):
    """Request handler: records requests, answers canned JSON."""

    def do_POST(self):  # pylint: disable=invalid-name  # http.server dispatch name
        """POST /v1/messages (or the configured failure)."""
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        headers = {k.lower(): v for k, v in self.headers.items()}
        self.server.requests.append((self.path, headers, body))
        if self.server.fail_with:
            self._send(self.server.fail_with, {"type": "error", "error": {
                "type": "overloaded_error", "message": "server says no"}})
            return
        if self.path != "/v1/messages":
            self._send(404, {})
            return
        req = json.loads(body)
        prompt = "\n".join(
            m["content"] if isinstance(m["content"], str) else m["content"][0]["text"]
            for m in req["messages"])
        self._send(200, {"id": "msg_1", "type": "message", "role": "assistant",
                         "model": req["model"],
                         "content": [{"type": "thinking", "thinking": "x"},
                                     {"type": "text", "text": reply_for(prompt)}],
                         "stop_reason": "end_turn"})


class AnthropicStub(JsonStub):  # pylint: disable=too-few-public-methods  # context-manager stub
    """Context-managed Anthropic-wire server; `fail_with` makes every call fail with that status."""

    def __init__(self, fail_with=None):
        super().__init__(_H, fail_with)
