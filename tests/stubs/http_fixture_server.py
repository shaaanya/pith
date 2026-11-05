"""Local HTTP fixture server for extractor tests (no internet). Routes: {path: Route}."""
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

FIXTURES = Path(__file__).parent.parent / "fixtures"


@dataclass
class Route:
    body: bytes | Path = b""
    status: int = 200
    ctype: str = "text/html; charset=utf-8"
    headers: dict = field(default_factory=dict)
    delay: float = 0.0
    content_length: bool = True  # False: HTTP/1.0 close-delimited body (no size announced)


class FixtureServer:
    def __init__(self, routes: dict[str, Route]):
        routes_ = routes

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                r = routes_.get(self.path.split("?")[0])
                if r is None:
                    r = Route(b"not found", 404, "text/plain")
                if r.delay:
                    time.sleep(r.delay)
                body = r.body.read_bytes() if isinstance(r.body, Path) else r.body
                self.send_response(r.status)
                self.send_header("Content-Type", r.ctype)
                if r.content_length:
                    self.send_header("Content-Length", str(len(body)))
                for k, v in r.headers.items():
                    self.send_header(k, v)
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass  # client gave up (size cap / timeout)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def __enter__(self):
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *a):
        self.httpd.shutdown()
        self.httpd.server_close()
