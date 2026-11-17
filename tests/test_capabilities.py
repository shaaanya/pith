"""Only capabilities a backend really implements can be declared or routed."""

import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from pith.config import Config
from pith.providers.openai_compat import OpenAICompatBackend
from pith.providers.ports import Capabilities, CapabilityError
from pith.providers import registry
from pith.providers.registry import Registry

PNG = b"\x89PNG\r\n\x1a\n" + b"fakeimage"


class _Handler(BaseHTTPRequestHandler):
    """Canned /chat/completions and /rerank answers; records every request body."""

    def log_message(self, *a):
        """Silence the request log."""

    def do_POST(self):  # pylint: disable=invalid-name  # http.server naming
        """Answer chat with a fixed description; rerank lists results in reverse order."""
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.seen.append((self.path, body))
        if self.path.endswith("/rerank"):
            n = len(body["documents"])
            out = {"results": [{"index": i, "relevance_score": float(n - 1 - i)}
                               for i in reversed(range(n))]}
        else:
            out = {"choices": [{"message": {"content": "a red quokka"}}]}
        raw = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


@pytest.fixture(name="server")
def _server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    srv.seen = []
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    srv.base = f"http://127.0.0.1:{srv.server_port}/v1"
    yield srv
    srv.shutdown()
    srv.server_close()


def _cfg(tmp_path, backends, tasks=None):
    return Config(home=tmp_path, db_path=tmp_path / "db", blobs_dir=tmp_path / "b",
                  vault_dir=tmp_path / "v", backends=backends, tasks=tasks or {})


def test_describe_sends_images_as_chat_image_parts(server, tmp_path):
    """vision -> describe() posts base64 image_url parts to the vision model and returns text."""
    img = tmp_path / "q.png"
    img.write_bytes(PNG)
    spec = {"type": "openai_compat", "base_url": server.base, "model": "chat",
            "vision_model": "eyes", "capabilities": ["vision"]}
    reg = Registry.from_config(_cfg(tmp_path, {"v": spec}))
    assert reg.first("describe").describe([img], "what is this?") == "a red quokka"
    path, body = server.seen[0]
    assert path == "/v1/chat/completions" and body["model"] == "eyes"
    text, image = body["messages"][0]["content"]
    assert text == {"type": "text", "text": "what is this?"}
    url = image["image_url"]["url"]
    assert url.startswith("data:image/png;base64,")
    assert base64.b64decode(url.split(",", 1)[1]) == PNG


def test_rerank_returns_scores_in_document_order(server, tmp_path):
    """rerank -> /rerank results are mapped back to input order by index."""
    spec = {"type": "openai_compat", "base_url": server.base, "model": "chat",
            "rerank_model": "ranker", "capabilities": ["rerank"]}
    reg = Registry.from_config(_cfg(tmp_path, {"r": spec}))
    assert reg.first("rerank").rerank("q", ["a", "b", "c"]) == [2.0, 1.0, 0.0]
    path, body = server.seen[0]
    assert path == "/v1/rerank" and body["model"] == "ranker" and body["query"] == "q"


def test_undeclared_vision_and_rerank_are_not_routed(server, tmp_path):
    """Without the declaration the backend is not in the chain and the method refuses."""
    spec = {"type": "openai_compat", "base_url": server.base, "model": "chat"}
    reg = Registry.from_config(_cfg(tmp_path, {"t": spec}))
    assert not reg.chain("describe") and not reg.chain("rerank")
    with pytest.raises(CapabilityError):
        reg.backends["t"].describe([], "x")
    with pytest.raises(CapabilityError):
        reg.backends["t"].rerank("q", ["a"])


@pytest.mark.parametrize("spec, msg", [
    ({"type": "openai_compat", "base_url": "http://localhost:1/v1", "model": "m",
      "capabilities": ["ocr"]}, "ocr"),
    ({"type": "openai_compat", "base_url": "http://localhost:1/v1", "model": "m",
      "capabilities": ["embeddings"]}, "embed_model"),
    ({"type": "cli", "command": ["x"], "capabilities": ["text", "vision"]}, "vision"),
    ({"type": "cli", "command": ["x"], "capabilities": ["embeddings"]}, "embeddings"),
])
def test_unimplemented_declared_capabilities_are_config_errors(tmp_path, spec, msg):
    """A declaration that nothing can serve fails at load, naming the capability."""
    with pytest.raises(ValueError, match=msg):
        Registry.from_config(_cfg(tmp_path, {"x": spec}))


def test_chain_requires_the_method_not_just_the_flag():
    """A backend flagged for a task but without the method is never returned."""
    liar = SimpleNamespace(name="liar", type="fake", locality="local",
                           capabilities=Capabilities(text=True, rerank=True, vision=True))
    reg = Registry({"liar": liar}, {"liar": {}}, {}, False)
    assert not reg.chain("rerank") and not reg.chain("describe")


class Liar(OpenAICompatBackend):
    """A backend that claims rerank without implementing it."""

    rerank = None


def test_real_backend_without_method_is_rejected_at_build(tmp_path, monkeypatch):
    """The registry cross-checks every declared flag against the real method."""
    monkeypatch.setitem(registry.TYPES, "liar", f"{__name__}:Liar")
    spec = {"type": "liar", "base_url": "http://localhost:1/v1", "model": "m",
            "capabilities": ["rerank"]}
    with pytest.raises(ValueError, match="rerank"):
        Registry.from_config(_cfg(tmp_path, {"x": spec}))
