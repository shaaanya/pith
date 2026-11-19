"""Dashboard api layer (called directly, no HTTP)."""
import hashlib

import pytest

from pith.dashboard import api
from pith.pipeline import runner
from pith.store.blobs import BlobStore
from pith.worker import Worker

NOTE = "Quokkas are small marsupials from Australia.\n\nThey live on Rottnest Island and eat grass."


def process(svc, _iid=None):
    """Run the worker until the queue is empty."""
    w = Worker(svc.conn, svc.inbox, svc.queue, lambda i: runner.process(svc, i))
    while w.run_once():
        pass


def test_blobstore_rejects_non_hex_sha(tmp_path):
    """The blob store rejects non-hex shas."""
    b = BlobStore(tmp_path)
    for bad in ("../../etc/passwd", "abc", "g" * 64, "A" * 64, ""):
        with pytest.raises(ValueError):
            b.path(bad)
    assert b.path("a" * 64).name == "a" * 64


def test_submit_list_detail_roundtrip(svc):
    """Submit, list and fetch detail."""
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
    """Bad submissions raise ValueError."""
    for bad in ({}, {"text": 5}, {"url": "ftp://x"}, {"text": "a", "url": "http://b.c"}):
        with pytest.raises(ValueError):
            api.inbox_submit(svc, bad)


def test_retry_and_clarify_flow(svc):
    """Retry and clarify transitions."""
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
    """Item edit, delete and reprocess."""
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
    """Search/ask shapes; non-http urls are dropped."""
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
    """Read-only summary endpoints."""
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
    """Blobs are served only for shas the database knows."""
    r = api.inbox_submit(svc, {"file": b"\x89PNG\r\n\x1a\n" + b"x" * 20, "filename": "p.png"})
    sha = svc.inbox.get(r["id"])["blob_sha256"]
    path, ctype, inline = api.blob(svc, sha)
    assert path.is_file() and ctype == "image/png" and inline
    svc.blobs.put_bytes(b"unreferenced")  # exists on disk but not known to the DB
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
    """Hostile strings come back as plain data."""
    evil = "<img src=x onerror=alert(1)>"
    text = evil + " quokkas marsupials live on Rottnest Island eat grass"
    r = api.inbox_submit(svc, {"text": text, "context": "javascript:alert(1)"})
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


def test_api_digest_uses_digest_module_and_never_writes(svc):
    """The digest endpoint is a dry run that writes nothing."""
    r = api.inbox_submit(svc, {"text": NOTE})
    process(svc, r["id"])
    d = api.digest(svc)
    assert d["total"] >= 1 and d["items"] and "## New" in d["markdown"]
    # dry-run: opening the dashboard must not use up the interval
    assert not (svc.cfg.home / "digests").exists()
    assert "egress" in api.privacy(svc)


def test_library_lists_notes_and_surfaces_attention(svc):
    """Library returns processed notes with a lead, and keeps failed/clarify items visible."""
    ok = api.inbox_submit(svc, {"text": NOTE, "context": "animals"})
    blank = api.inbox_submit(svc, {"text": "   "})
    process(svc)
    lib = api.library(svc, {})
    assert lib["total"] >= 1 and lib["items"][0]["lead"] and lib["next"] is None
    assert [r["id"] for r in lib["attention"]] == [blank["id"]]
    assert api.inbox_get(svc, ok["id"])["status"] == "processed"
    assert api.library(svc, {"type": "pdf"})["items"] == []
    assert api.library(svc, {"before": f"{lib['items'][0]['created_at']}|0"})["items"] == []


def test_search_hits_open_a_note(svc):
    """Every hit carries note_id so a segment or unit hit opens the whole note."""
    api.inbox_submit(svc, {"text": NOTE})
    process(svc)
    hits = api.search(svc, "quokkas", {})["hits"]
    notes = {i["id"] for i in api.library(svc, {})["items"]}
    assert hits and all(h["note_id"] in notes for h in hits)


def test_item_note_appends_context_and_requeues(svc):
    """A note added after saving is kept as context and the item is processed again."""
    r = api.inbox_submit(svc, {"text": NOTE})
    process(svc, r["id"])
    iid = api.inbox_get(svc, r["id"])["items"][0]["id"]
    out = api.item_note(svc, iid, {"text": "only the island"})
    assert out == {"ok": True, "inbox_id": r["id"]}
    assert api.inbox_get(svc, r["id"])["status"] == "pending"
    api.item_note(svc, iid, {"text": "only the island"})  # same text is not stored twice
    ctx = svc.conn.execute("SELECT user_note FROM inbox_items WHERE id=?", (r["id"],)).fetchone()
    assert ctx[0] == "only the island"
    for bad in ({}, {"text": ""}, {"text": 5}, {"text": "x", "extra": 1}):
        with pytest.raises(ValueError):
            api.item_note(svc, iid, bad)
    with pytest.raises(KeyError):
        api.item_note(svc, "nope", {"text": "x"})


def test_item_note_counts_as_the_reason_even_for_machine_written_adapters(svc):
    """Drop-folder items carry "from a.txt" as provenance; a note you add is still your reason."""
    r = svc.inbox.submit(adapter="fs", text=NOTE, user_context="from a.txt")
    process(svc)
    assert runner.intent_of(svc.inbox.get(r.id)) is None
    iid = api.inbox_get(svc, r.id)["items"][0]["id"]
    api.item_note(svc, iid, {"text": "only the island"})
    assert runner.intent_of(svc.inbox.get(r.id)) == "only the island"
    api.item_note(svc, iid, {"text": "only the island"})
    api.item_note(svc, iid, {"text": "and the grass"})
    assert runner.intent_of(svc.inbox.get(r.id)) == "only the island\n\nand the grass"


def _processed_note(svc, text=NOTE, **kw):
    r = api.inbox_submit(svc, {"text": text, **kw})
    process(svc, r["id"])
    return r["id"], api.inbox_get(svc, r["id"])["items"][0]["id"]


def test_items_carry_shelf_and_placement_and_can_be_moved(svc):
    inbox_id, iid = _processed_note(svc)
    lib = api.library(svc, {})["items"][0]
    assert lib["shelf"] in ("reference", "other") and lib["placement"]["by"] in ("default", "none")
    assert api.item_detail(svc, iid)["shelf"] == lib["shelf"]
    out = api.item_update(svc, iid, {"shelf": "try"})
    assert out["shelf"] == "try" and out["placement"] == {"by": "you", "why": "You put it here"}
    assert api.library(svc, {"shelf": "try"})["total"] == 1
    assert api.library(svc, {"shelf": "watch"})["total"] == 0
    api.item_update(svc, iid, {"shelf": "read", "title": "Renamed"})
    assert api.item_detail(svc, iid)["title"] == "Renamed"
    api.item_reprocess(svc, iid)
    process(svc)
    assert api.library(svc, {"shelf": "read"})["total"] == 1  # the move survives reprocess
    with pytest.raises(ValueError):
        api.item_update(svc, iid, {"shelf": "nope"})
    with pytest.raises(ValueError):
        api.item_update(svc, iid, {"shelf": 5})
    assert inbox_id


def test_rule_placement_is_reported_as_reason_or_site(svc):
    _, iid = _processed_note(svc, context="a film to watch")
    assert api.item_detail(svc, iid)["placement"]["by"] == "reason"
    assert api.item_detail(svc, iid)["shelf"] == "watch"


def test_shelves_crud_counts_and_rules(svc):
    _, iid = _processed_note(svc)
    got = api.shelves(svc)["shelves"]
    assert [s["id"] for s in got][-1] == "other" and all("count" in s for s in got)
    assert sum(s["count"] for s in got) == 1
    made = api.shelf_create(svc, {"name": "Recipes", "blurb": "Dishes to cook"})
    assert made["id"] == "recipes" and made["count"] == 0
    api.item_update(svc, iid, {"shelf": "recipes"})
    assert {s["id"]: s["count"] for s in api.shelves(svc)["shelves"]}["recipes"] == 1
    assert api.shelf_update(svc, "recipes", {"blurb": "x"})["blurb"] == "x"
    for bad in ({}, {"name": ""}, {"name": "Recipes"}, {"name": 5}):
        with pytest.raises(ValueError):
            api.shelf_create(svc, bad)
    with pytest.raises(ValueError):
        api.shelf_update(svc, "recipes", {"bogus": 1})
    with pytest.raises(KeyError):
        api.shelf_update(svc, "nope", {"name": "x"})
    api.shelf_delete(svc, "recipes")
    assert api.item_detail(svc, iid)["shelf"] == "other"
    for builtin in ("other", "watch"):
        with pytest.raises(ValueError):
            api.shelf_delete(svc, builtin)
    with pytest.raises(KeyError):
        api.shelf_delete(svc, "nope")


def test_note_state_done_snooze_hidden_viewed_and_filters(svc):
    _, iid = _processed_note(svc)
    d = api.item_detail(svc, iid)
    assert d["state"] == {"done_at": None, "snooze_until": None, "hidden": False}
    assert d["last_viewed_at"] is None
    out = api.item_update(svc, iid, {"done": True, "hidden": True,
                                     "snooze_until": "2031-01-01T00:00:00Z"})
    assert out["state"]["done_at"] and out["state"]["hidden"]
    it = api.library(svc, {})["items"][0]
    assert it["state"]["done_at"] and it["last_viewed_at"] is None
    assert api.library(svc, {"done": "1"})["total"] == 1 and api.library(svc, {"done": "0"})["total"] == 0
    api.item_viewed(svc, iid)
    assert api.item_detail(svc, iid)["last_viewed_at"]
    assert [i["id"] for i in api.library(svc, {"viewed": "1"})["items"]] == [iid]
    api.item_update(svc, iid, {"done": False, "snooze_until": None})
    assert api.library(svc, {"done": "0"})["total"] == 1
    assert api.library(svc, {"viewed": "1"})["total"] == 1
    for bad in ({"done": "yes"}, {"hidden": 1}, {"snooze_until": "soon"}):
        with pytest.raises(ValueError):
            api.item_update(svc, iid, bad)
    with pytest.raises(KeyError):
        api.item_viewed(svc, "nope")


def test_state_survives_reprocess_and_shelf_todo_count_follows_done(svc):
    _, iid = _processed_note(svc, context="a film to watch")
    watch = lambda: next(s for s in api.shelves(svc)["shelves"] if s["id"] == "watch")
    assert watch()["todo_count"] == 1
    api.item_update(svc, iid, {"done": True})
    assert watch()["count"] == 1 and watch()["todo_count"] == 0
    api.item_reprocess(svc, iid)
    process(svc)
    assert api.library(svc, {"done": "1"})["total"] == 1


def test_entries_listing_ticking_and_survive_reprocess(svc):
    from pith.store import entries as ent
    _, iid = _processed_note(svc, context="a film to watch")
    owner = svc.conn.execute("SELECT source_id FROM knowledge_items WHERE id=?", (iid,)).fetchone()[0]
    ent.sync(svc.conn, owner, iid, ["Paper Moon Harbor", "The Long Dissolve"])
    d = api.item_detail(svc, iid)
    assert [e["text"] for e in d["entries"]] == ["Paper Moon Harbor", "The Long Dissolve"]
    eid = d["entries"][0]["id"]
    assert api.entry_update(svc, eid, {"done": True})["done_at"]
    got = api.entries(svc, {"shelf": "watch"})["entries"]
    assert len(got) == 2 and got[0]["note"]["id"] == iid and got[0]["note"]["shelf"] == "watch"
    assert [e["text"] for e in api.entries(svc, {"done": "0"})["entries"]] == ["The Long Dissolve"]
    assert api.entries(svc, {"shelf": "play"})["entries"] == []
    with pytest.raises(ValueError):
        api.entry_update(svc, eid, {"done": "x"})
    with pytest.raises(KeyError):
        api.entry_update(svc, "nope", {"done": True})


def test_resurface_endpoint_is_empty_without_a_reason(svc):
    _processed_note(svc)
    assert api.resurface(svc) == {"items": []}


def test_shelf_null_lets_pith_decide_again(svc):
    _, iid = _processed_note(svc, context="a film to watch")
    api.item_update(svc, iid, {"shelf": "play"})
    assert api.item_detail(svc, iid)["placement"]["by"] == "you"
    out = api.item_update(svc, iid, {"shelf": None})
    assert out["shelf"] == "watch" and out["placement"]["by"] == "reason"
