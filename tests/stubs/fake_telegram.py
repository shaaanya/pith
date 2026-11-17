"""A local fake of the bits of the Telegram Bot API the receive-only channel uses."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeTelegram:
    """Context manager: serves getUpdates, getFile and file downloads on 127.0.0.1."""
    token = "123456:SECRET-TOKEN"

    def __init__(self):
        self.updates, self.files, self.requests, self._fail = [], {}, [], []
        self.fail_sends = False  # sendMessage answers 500 while True
        self.broken = set()  # file ids whose download answers 404 although getFile succeeded
        self._next_id = 100
        self.server = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def queue_update(self, update: dict) -> int:
        """Add an update (gets the next update_id); returns that id."""
        self._next_id += 1
        self.updates.append({"update_id": self._next_id, **update})
        return self._next_id

    def message(self, chat: int = 7, text: str | None = None, **extra) -> int:
        """Queue a plain message update; message_id equals the update_id."""
        mid = self._next_id + 1
        msg = {"message_id": mid, "chat": {"id": chat}, **extra}
        if text is not None:
            msg["text"] = text
        return self.queue_update({"message": msg})

    def fail_next(self, status: int) -> None:
        """The next API request answers with this HTTP status."""
        self._fail.append(status)

    def sent(self) -> list[tuple[int, str]]:
        """(chat_id, text) of every sendMessage request so far."""
        return [(b["chat_id"], b["text"]) for path, b in self.requests if path.endswith("/sendMessage")]

    def getupdates_bodies(self) -> list[dict]:
        """Bodies of every getUpdates request so far."""
        return [b for path, b in self.requests if path.endswith("/getUpdates")]

    def __enter__(self):
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_a):
                pass

            def _send(self, status, payload, raw=False):
                data = payload if raw else json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):  # file download
                prefix = f"/file/bot{fake.token}/files/"
                fid = self.path[len(prefix):]
                if self.path.startswith(prefix) and fid in fake.files and fid not in fake.broken:
                    return self._send(200, fake.files[fid], raw=True)
                return self._send(404, {"ok": False})

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
                fake.requests.append((self.path, body))
                if fake._fail:
                    return self._send(fake._fail.pop(0), {"ok": False, "description": "nope"})
                if not self.path.startswith(f"/bot{fake.token}/"):
                    return self._send(401, {"ok": False, "description": "Unauthorized"})
                method = self.path.rsplit("/", 1)[1]
                if method == "sendMessage":
                    if fake.fail_sends:
                        return self._send(500, {"ok": False, "description": "boom"})
                    return self._send(200, {"ok": True, "result": {"message_id": 1}})
                if method == "getMe":
                    return self._send(200, {"ok": True, "result": {"id": 1, "is_bot": True,
                                                                    "username": "pith_test_bot"}})
                if method == "getUpdates":
                    off = body.get("offset", 0)
                    return self._send(200, {"ok": True, "result": [
                        u for u in fake.updates if u["update_id"] >= off]})
                if method == "getFile" and body.get("file_id") in fake.files:
                    fid = body["file_id"]
                    return self._send(200, {"ok": True, "result": {
                        "file_id": fid, "file_path": f"files/{fid}"}})
                return self._send(400, {"ok": False, "description": "bad request"})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *_exc):
        self.server.shutdown()
        self.server.server_close()
