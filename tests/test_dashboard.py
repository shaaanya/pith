"""Dashboard HTTP API: auth, headers, routing, uploads and item/inbox flows."""
import http.client
import json
import threading

import pytest

from pith.adapters.http_ingest import load_token
from pith.dashboard import api
from pith.dashboard.server import make_server
from pith.worker import Worker
from pith.pipeline import runner

NOTE = "Quokkas are small marsupials from Australia.\n\nThey live on Rottnest Island and eat grass."


class Client:  # pylint: disable=too-few-public-methods  # one-method HTTP test helper
    """Tiny HTTP client for the dashboard (token header, or cookie when `cookie`)."""

    def __init__(self, srv, token=None, cookie=False):
        self.port, self.token, self.cookie = srv.server_address[1], token, cookie

    def req(self, method, path, body=None, headers=None, raw=None):  # pylint: disable=too-many-arguments,too-many-positional-arguments  # optional helper args
        """One request; returns (status, json-or-bytes, response)."""
        h = {"Host": f"127.0.0.1:{self.port}", **(headers or {})}
        if self.token and self.cookie:
            h["Cookie"] = f"ip_token={self.token}"
        elif self.token:
            h["X-Token"] = self.token
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        if data is not None and "Content-Type" not in h:
            h["Content-Type"] = "application/json"
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request(method, path, body=data, headers=h)
        r = c.getresponse()
        payload = r.read()
        c.close()
        try:
            obj = json.loads(payload)
        except ValueError:
            obj = payload
        return r.status, obj, r


@pytest.fixture(name="srv")
def srv_fixture(svc):
    """A dashboard server on an ephemeral loopback port."""
    s = make_server(svc, port=0)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield s
    s.shutdown()
    s.server_close()


@pytest.fixture(name="client")
def client_fixture(srv, svc):
    """Authenticated client for the server."""
    return Client(srv, load_token(svc.cfg))


def drain(svc):
    """Run the worker until the queue is empty."""
    w = Worker(svc.conn, svc.inbox, svc.queue, lambda i: runner.process(svc, i))
    while w.run_once():
        pass


def test_server_rejects_non_loopback(svc):
    """A non-loopback bind without an explicit token is refused."""
    with pytest.raises(ValueError):
        make_server(svc, host="0.0.0.0", port=0)
    with pytest.raises(ValueError):
        make_server(svc, host="192.168.1.5", port=0)


def test_auth_required_and_cookie_bootstrap(srv, client):
    """Token auth, cookie bootstrap via ?token=, and the unauthenticated page."""
    anon = Client(srv)
    assert anon.req("GET", "/api/inbox")[0] == 401
    st, _, r = anon.req("GET", f"/?token={client.token}")
    assert st == 302 and r.getheader("Location") == "/"
    cookie = r.getheader("Set-Cookie")
    assert "HttpOnly" in cookie and "SameSite=Strict" in cookie and "ip_token=" in cookie
    assert "Max-Age=604800" in cookie
    assert Client(srv, client.token, cookie=True).req("GET", "/api/inbox")[0] == 200
    assert Client(srv, "wrong").req("GET", "/api/inbox")[0] == 401
    st, page, r = anon.req("GET", "/")
    assert st == 200 and b"<html" in page


def test_security_headers_and_csp(client):
    """Strict CSP with a fresh nonce per response; no CORS header."""
    _, page, r = client.req("GET", "/")
    csp = r.getheader("Content-Security-Policy")
    assert "default-src 'none'" in csp and "unsafe-inline" not in csp
    assert "http" not in csp.replace("https:", "")
    assert r.getheader("X-Content-Type-Options") == "nosniff"
    assert r.getheader("X-Frame-Options") == "DENY"
    nonce = csp.split("'nonce-")[1].split("'")[0]
    assert f'nonce="{nonce}"'.encode() in page and b"{{nonce}}" not in page
    _, _, r2 = client.req("GET", "/")
    assert r2.getheader("Content-Security-Policy") != csp  # fresh nonce per response
    assert "Access-Control-Allow-Origin" not in dict(r.getheaders())


def test_host_allow_list_blocks_dns_rebinding(client):
    """Foreign Host headers are rejected."""
    assert client.req("GET", "/api/inbox", headers={"Host": "evil.example:80"})[0] == 403
    assert client.req("GET", "/", headers={"Host": "evil.example"})[0] == 403
    assert client.req("GET", "/api/inbox", headers={"Host": f"localhost:{client.port}"})[0] == 200


def test_csrf_origin_check_on_cookie_auth(srv, svc):
    """Cookie-authenticated writes need a same-origin Origin header."""
    tok = load_token(svc.cfg)
    c = Client(srv, tok, cookie=True)
    body = {"text": NOTE}
    assert c.req("POST", "/api/inbox", body)[0] == 403  # cookie auth without Origin
    assert c.req("POST", "/api/inbox", body, headers={"Origin": "http://evil.example"})[0] == 403
    ok = c.req("POST", "/api/inbox", body, headers={"Origin": f"http://127.0.0.1:{c.port}"})
    assert ok[0] == 200
    # reads are fine
    assert c.req("GET", "/api/inbox", headers={"Origin": "http://evil.example"})[0] == 200


def test_api_inbox_submit_then_list(client):
    """Submit through the API, list it, and reject bad bodies with 400."""
    st, out, _ = client.req("POST", "/api/inbox", {"text": NOTE, "context": "animals"})
    assert st == 200 and out["id"]
    st, rows, _ = client.req("GET", "/api/inbox?status=pending")
    assert [r["id"] for r in rows] == [out["id"]]
    assert client.req("POST", "/api/inbox", {"url": "javascript:alert(1)"})[0] == 400
    assert client.req("POST", "/api/inbox", raw=b"{not json")[0] == 400
    assert client.req("POST", "/api/inbox", raw=b"[1]")[0] == 400


def test_multipart_upload_and_size_cap(client, svc):
    """Multipart upload works and oversized JSON bodies are rejected."""
    b = "XBOUND"
    raw = (f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="n.txt"'
           f'\r\n\r\n{NOTE}\r\n--{b}--\r\n').encode()
    ctype = f"multipart/form-data; boundary={b}"
    st, out, _ = client.req("POST", "/api/inbox", raw=raw, headers={"Content-Type": ctype})
    assert st == 200 and svc.inbox.get(out["id"])["original_filename"] == "n.txt"
    big = b"{" + b" " * (2 * 1024 * 1024) + b"}"
    try:
        assert client.req("POST", "/api/inbox", raw=big)[0] == 413  # JSON bodies are capped at 1 MB
    except (BrokenPipeError, ConnectionResetError):
        pass  # server answered 413 and closed before the client finished sending: also a rejection


def test_api_item_edit_delete_reprocess(client, svc):
    """Item detail, edit validation, reprocess and delete."""
    _, out, _ = client.req("POST", "/api/inbox", {"text": NOTE})
    drain(svc)
    iid = client.req("GET", f"/api/inbox/{out['id']}")[1]["items"][0]["id"]
    st, item, _ = client.req("GET", f"/api/items/{iid}")
    assert st == 200 and item["source"]["id"] and "provenance" in item
    assert client.req("PATCH", f"/api/items/{iid}", {"title": "Edited"})[1]["title"] == "Edited"
    assert client.req("PATCH", f"/api/items/{iid}", {"title": 3})[0] == 400
    assert client.req("POST", f"/api/items/{iid}/reprocess", {})[0] == 200
    assert client.req("DELETE", f"/api/items/{iid}")[0] == 200
    assert client.req("GET", f"/api/items/{iid}")[0] == 404
    assert client.req("GET", "/api/items/nope")[0] == 404


def test_api_blob_path_traversal_blocked(client, svc):
    """Blob serving is by exact sha only; unsafe types download as attachments."""
    octet = {"Content-Type": "application/octet-stream"}
    _, out, _ = client.req("POST", "/api/inbox", raw=b"\x89PNG\r\n\x1a\nxxxx",
                           headers={**octet, "X-Filename": "p.png"})
    sha = svc.inbox.get(out["id"])["blob_sha256"]
    st, _, r = client.req("GET", f"/api/blob/{sha}")
    assert st == 200 and r.getheader("Content-Type") == "image/png"
    assert r.getheader("X-Content-Type-Options") == "nosniff"
    for bad in ("..%2F..%2Fetc%2Fpasswd", "../../etc/passwd", "%2e%2e/x", "a" * 63, "g" * 64,
                sha + "/../x"):
        st, _, _ = client.req("GET", f"/api/blob/{bad}")
        assert st in (400, 404), bad
    _, o2, _ = client.req("POST", "/api/inbox", raw=b"<script>alert(1)</script>",
                          headers={**octet, "X-Filename": "x.html"})
    st, _, r = client.req("GET", f"/api/blob/{svc.inbox.get(o2['id'])['blob_sha256']}")
    assert st == 200 and "attachment" in r.getheader("Content-Disposition")
    assert r.getheader("Content-Type") == "application/octet-stream"


def test_api_search_and_ask_shapes(client, svc):
    """Search/ask response shapes and the read-only summary endpoints."""
    client.req("POST", "/api/inbox", {"text": NOTE})
    drain(svc)
    st, s, _ = client.req("GET", "/api/search?q=quokkas&kind=&topic=")
    assert st == 200 and s["hits"] and "mode" in s and isinstance(s["warnings"], list)
    st, a, _ = client.req("POST", "/api/ask", {"q": "Where do quokkas live?"})
    assert st == 200 and a["mode"] in ("answer", "retrieval-only") and a["retrieved"]
    assert client.req("POST", "/api/ask", {"q": ""})[0] == 400
    for p in ("/api/topics", "/api/duplicates", "/api/digest", "/api/privacy", "/api/state"):
        assert client.req("GET", p)[0] == 200, p


def test_errors_are_json_never_tracebacks(client, monkeypatch):
    """Handler errors are a generic JSON 500; unknown path 404, wrong method 405."""
    monkeypatch.setattr(api, "topics", lambda s: 1 / 0)
    st, out, _ = client.req("GET", "/api/topics")
    assert st == 500 and out == {"error": "internal error"}
    assert client.req("GET", "/api/nope")[0] == 404
    assert client.req("PUT", "/api/inbox")[0] == 405
    assert client.req("GET", "/static/../../etc/passwd")[0] == 404


def test_handler_returning_none_is_json_null_not_a_hang(client, monkeypatch):
    """A handler returning None answers JSON null instead of hanging."""
    monkeypatch.setattr(api, "topics", lambda s: None)
    st, out, _ = client.req("GET", "/api/topics")
    assert st == 200 and out is None


ROUTE_STATUS = [
    ("GET", "/api/inbox/abc/retry", 405), ("PUT", "/api/items/abc", 405),
    ("POST", "/api/blob/x", 405), ("PUT", "/api/inbox", 405),
    ("POST", "/api/search", 404), ("GET", "/api/ask", 404), ("POST", "/api/topics", 404),
    ("GET", "/api/nope", 404), ("HEAD", "/api/topics", 200), ("HEAD", "/api/nope", 404),
    ("HEAD", "/api/ask", 404),
]


@pytest.mark.parametrize(("method", "path", "status"), ROUTE_STATUS)
def test_route_table_404_vs_405_vs_head(client, method, path, status):
    """Unknown path 404; known resource with a bad method 405; HEAD follows GET."""
    assert client.req(method, path)[0] == status


def test_head_has_no_body(client):
    """HEAD sends headers (with a length) and no body."""
    st, body, r = client.req("HEAD", "/api/topics")
    assert st == 200 and body == b"" and int(r.getheader("Content-Length")) > 0


def test_inbox_clarify_and_retry_over_http(client, svc):
    """Clarify and retry flows over HTTP, 404 for unknown ids."""
    _, out, _ = client.req("POST", "/api/inbox", {"text": "   "})
    drain(svc)
    assert client.req("GET", f"/api/inbox/{out['id']}")[1]["status"] == "needs_clarification"
    assert client.req("POST", f"/api/inbox/{out['id']}/clarify", {"text": NOTE})[0] == 200
    drain(svc)
    assert client.req("GET", f"/api/inbox/{out['id']}")[1]["status"] == "processed"
    svc.inbox.set_status(out["id"], "failed", "boom")
    assert client.req("POST", f"/api/inbox/{out['id']}/retry", {})[0] == 200
    assert client.req("POST", "/api/inbox/nope/retry", {})[0] == 404
