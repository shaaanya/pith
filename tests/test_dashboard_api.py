import pytest

from infoparser.dashboard import api
from infoparser.pipeline import runner
from infoparser.store.blobs import BlobStore

NOTE = "Quokkas are small marsupials from Australia.\n\nThey live on Rottnest Island and eat grass."


def process(svc, iid):
    from infoparser.worker import Worker
    w = Worker(svc.conn, svc.inbox, svc.queue, lambda i: runner.process(svc, i))
    while w.run_once():
        pass


def test_blobstore_rejects_non_hex_sha(tmp_path):
    b = BlobStore(tmp_path)
    for bad in ("../../etc/passwd", "abc", "g" * 64, "A" * 64, ""):
        with pytest.raises(ValueError):
            b.path(bad)
    assert b.path("a" * 64).name == "a" * 64


def test_submit_list_detail_roundtrip(svc):
    r = api.inbox_submit(svc, {"text": NOTE, "context": "animals"})
    rows = api.inbox_list(svc, None)
    assert rows[0]["id"] == r["id"] and rows[0]["status"] == "pending"
    process(svc, r["id"])
    d = api.inbox_get(svc, r["id"])
    assert d["status"] == "processed" and d["items"] and d["events"]
    item = api.item_detail(svc, d["items"][0]["id"])
    assert item["provenance"] in ("stated", "inferred", "external")
    assert item["source"]["id"] and item["citations"] is not None and item["inbox"]


def test_inbox_submit_validation(svc):
    for bad in ({}, {"text": 5}, {"url": "ftp://x"}, {"text": "a", "url": "http://b.c"}):
        with pytest.raises(ValueError):
            api.inbox_submit(svc, bad)


def test_retry_and_clarify_flow(svc):
    r = api.inbox_submit(svc, {"text": "   "})  # empty -> needs_clarification
    process(svc, r["id"])
    assert api.inbox_get(svc, r["id"])["status"] == "needs_clarification"
    with pytest.raises(ValueError):
        api.clarify(svc, r["id"], "  ")
    note = api.clarify(svc, r["id"], NOTE)
    assert note["ok"] and "login" in note["note"] and "cannot fix" in note["note"]
    row = api.inbox_get(svc, r["id"])
    assert row["status"] == "pending" and NOTE in row["user_context"]
    with pytest.raises(KeyError):
        api.clarify(svc, "nope", "x")
    svc.inbox.set_status(r["id"], "failed", "boom")
    api.retry(svc, r["id"])
    assert api.inbox_get(svc, r["id"])["status"] == "pending"
    with pytest.raises(KeyError):
        api.retry(svc, "nope")


def test_item_edit_delete_reprocess(svc):
    r = api.inbox_submit(svc, {"text": NOTE})
    process(svc, r["id"])
    iid = api.inbox_get(svc, r["id"])["items"][0]["id"]
    out = api.item_update(svc, iid, {"title": "New title", "body": "New body"})
    assert out["title"] == "New title" and out["user_edited"]
    for bad in ({}, {"title": 5}, {"bogus": "x"}, {"title": "x" * 10_000}):
        with pytest.raises(ValueError):
            api.item_update(svc, iid, bad)
    api.item_reprocess(svc, iid)
    assert api.inbox_get(svc, r["id"])["status"] == "pending"
    process(svc, r["id"])
    assert api.item_detail(svc, iid)["title"] == "New title"  # user edit survives
    api.item_delete(svc, iid)
    with pytest.raises(KeyError):
        api.item_detail(svc, iid)
    with pytest.raises(KeyError):
        api.item_update(svc, "nope", {"title": "x"})


def test_search_and_ask_shapes_and_url_sanitising(svc):
    r = api.inbox_submit(svc, {"text": NOTE})
    process(svc, r["id"])
    s = api.search(svc, "quokkas", {})
    assert set(s) >= {"mode", "warnings", "egress", "hits"} and s["hits"]
    assert {"item_id", "title", "snippet", "provenance", "kind"} <= set(s["hits"][0])
    assert api.search(svc, "", {})["hits"] == []
    a = api.ask(svc, "Where do quokkas live?")
    assert a["mode"] == "retrieval-only" and a["retrieved"] and "message" in a and "warnings" in a
    assert api.safe_url("javascript:alert(1)") is None and api.safe_url("data:text/html,x") is None
    assert api.safe_url("https://a.b/c") == "https://a.b/c" and api.safe_url(None) is None
    with pytest.raises(ValueError):
        api.ask(svc, "")


def test_topics_duplicates_digest_state_privacy(svc):
    r = api.inbox_submit(svc, {"text": NOTE})
    process(svc, r["id"])
    assert isinstance(api.topics(svc), list)
    assert isinstance(api.duplicates(svc), list)
    d = api.digest(svc)
    assert d["total"] >= 1 and d["items"]
    st = api.state(svc)
    assert st["counts"]["processed"] == 1 and "backends" in st
    p = api.privacy(svc)
    assert p["allow_remote"] is False and "backends" in p


def test_blob_lookup_only_by_known_sha(svc):
    r = api.inbox_submit(svc, {"file": b"\x89PNG\r\n\x1a\n" + b"x" * 20, "filename": "p.png"})
    sha = svc.inbox.get(r["id"])["blob_sha256"]
    path, ctype, inline = api.blob(svc, sha)
    assert path.is_file() and ctype == "image/png" and inline
    svc.blobs.put_bytes(b"unreferenced")  # exists on disk but not known to the DB
    import hashlib
    with pytest.raises(KeyError):
        api.blob(svc, hashlib.sha256(b"unreferenced").hexdigest())
    for bad in ("../x", "zz", "a" * 63):
        with pytest.raises(ValueError):
            api.blob(svc, bad)
    r2 = api.inbox_submit(svc, {"file": b"<html><script>alert(1)</script>", "filename": "x.html"})
    sha2 = svc.inbox.get(r2["id"])["blob_sha256"]
    _, ctype2, inline2 = api.blob(svc, sha2)
    assert not inline2 and ctype2 == "application/octet-stream"


def test_hostile_strings_come_back_as_plain_data(svc):
    evil = "<img src=x onerror=alert(1)>"
    r = api.inbox_submit(svc, {"text": evil + " quokkas marsupials live on Rottnest Island eat grass", "context": "javascript:alert(1)"})
    rows = api.inbox_list(svc, None)
    assert rows[0]["what"].startswith(evil) and rows[0]["url"] is None  # data, never markup
    assert rows[0]["user_context"] == "javascript:alert(1)"
    process(svc, r["id"])
    iid = api.inbox_get(svc, r["id"])["items"][0]["id"]
    api.item_update(svc, iid, {"title": evil})
    assert api.item_detail(svc, iid)["title"] == evil
    svc.conn.execute("UPDATE sources SET url='javascript:alert(1)'")
    d = api.item_detail(svc, iid)
    assert d["source"]["url"] is None
    assert all(h["source_url"] is None for h in api.search(svc, "quokkas", {})["hits"])
