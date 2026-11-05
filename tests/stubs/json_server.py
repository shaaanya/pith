"""Shared pieces of the loopback JSON stub servers (OpenAI-wire and Anthropic-wire)."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class JsonHandler(BaseHTTPRequestHandler):
    """Silent handler with a JSON `_send`."""

    def log_message(self, *a):  # pylint: disable=arguments-differ  # silence request logging
        """No request logging."""

    def _send(self, code, obj):
        """Write a JSON response."""
        raw = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class JsonStub:  # pylint: disable=too-few-public-methods  # context manager + base_url
    """Context-managed loopback server; `requests` records (path, headers, body)."""

    url_suffix = ""

    def __init__(self, handler, fail_with=None):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.server.requests, self.server.fail_with = [], fail_with
        self.requests = self.server.requests

    @property
    def base_url(self):
        """Root url of the running server."""
        return f"http://127.0.0.1:{self.server.server_port}{self.url_suffix}"

    def __enter__(self):
        """Start serving."""
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05},
                         daemon=True).start()
        return self

    def __exit__(self, *exc):
        """Stop serving."""
        self.server.shutdown()
        self.server.server_close()
