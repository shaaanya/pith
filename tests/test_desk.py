"""Real desk HTTP and storage contract: durable organization, no fixture knowledge."""
import threading

import pytest

from pith.dashboard.server import make_server
from pith.domain.models import Candidate
from pith.store import desk, knowledge
from pith.store.db import connect
from test_dashboard import Client


@pytest.fixture(name="desk_server")
def desk_server_fixture(svc):
    """An actual loopback dashboard over the test home."""
    server = make_server(svc, port=0, token="desk-test-token")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()
    thread.join()


@pytest.fixture(name="desk_client")
def desk_client_fixture(desk_server):
    """Header-authenticated desk API client."""
    return Client(desk_server, "desk-test-token")


def note(svc, title="My saved note"):
    """Insert actual product knowledge without a remote model."""
    (iid,) = knowledge.save_items(svc.conn, None, [Candidate(kind="note", title=title, body="Text")],
                                  "test", [])
    return iid


def group(gid="group-one", ids=(), **extra):
    """A complete organization group as sent by the product client."""
    return {"id": gid, "title": "Weekend research", "description": "A mixed context",
            "icon": "bookmark", "focused": False, "item_ids": list(ids), **extra}


def test_desk_http_round_trip_persistence_and_safe_group_removal(svc, desk_client):
    """Editing, membership, order, Focus and deletion persist without deleting notes."""
    first, second = note(svc), note(svc, "Another saved note")
    assert desk_client.req("GET", "/api/desk")[:2] == (200, {"revision": 0, "groups": []})
    groups = [group(ids=[second, first], focused=True), group("group-two", [first])]
    status, saved, _ = desk_client.req("PATCH", "/api/desk", {"revision": 0, "groups": groups})
    assert status == 200 and saved["revision"] == 1
    assert [g["id"] for g in saved["groups"]] == ["group-one", "group-two"]
    assert saved["groups"][0]["focused"] is True
    assert saved["groups"][0]["item_ids"] == [second, first]
    assert [i["title"] for i in saved["groups"][0]["items"]] == ["Another saved note", "My saved note"]
    conn = connect(svc.cfg.db_path)
    try:
        assert desk.read(conn) == saved
    finally:
        conn.close()
    # Undo can restore a previous full organization using the current revision.
    assert desk_client.req("PATCH", "/api/desk", {"revision": 1, "groups": []})[0] == 200
    assert desk_client.req("PATCH", "/api/desk", {"revision": 2, "groups": groups})[0] == 200
    assert svc.conn.execute("SELECT count(*) FROM knowledge_items WHERE deleted_at IS NULL").fetchone()[0] == 2


def test_desk_stale_revision_returns_409_without_losing_saved_changes(desk_client):
    """A stale browser cannot silently overwrite another browser's groups."""
    assert desk_client.req("PATCH", "/api/desk", {"revision": 0, "groups": [group()]})[0] == 200
    status, body, _ = desk_client.req("PATCH", "/api/desk", {"revision": 0, "groups": []})
    assert status == 409 and "another window" in body["error"]
    assert len(desk_client.req("GET", "/api/desk")[1]["groups"]) == 1


@pytest.mark.parametrize("body", [
    None, [], {}, {"revision": True, "groups": []}, {"revision": -1, "groups": []},
    {"revision": 0, "groups": [group(title=" ")]},
    {"revision": 0, "groups": [group(title="x" * 81)]},
    {"revision": 0, "groups": [group(description="x" * 141)]},
    {"revision": 0, "groups": [group(icon="bad")]},
    {"revision": 0, "groups": [group(focused=1)]},
    {"revision": 0, "groups": [group(ids=["unknown"])]},
    {"revision": 0, "groups": [group(ids=["same", "same"])]},
    {"revision": 0, "groups": [group(ids=[{}])]},
    {"revision": 0, "groups": [group(gid="has spaces")]},
    {"revision": 0, "groups": [group(), group()]},
    {"revision": 0, "groups": [group(str(i)) for i in range(201)]},
])
def test_invalid_desk_updates_are_atomic(svc, body):
    """Malformed or stale/deleted membership never leaves a half-written desk."""
    with pytest.raises(ValueError):
        desk.replace(svc.conn, body)
    assert desk.read(svc.conn) == {"revision": 0, "groups": []}


def test_deleted_notes_are_excluded_and_cannot_be_selected(svc, desk_client):
    """Soft-deleted knowledge disappears from groups and cannot be reintroduced."""
    iid = note(svc)
    assert desk_client.req("PATCH", "/api/desk", {"revision": 0, "groups": [group(ids=[iid])]})[0] == 200
    assert desk_client.req("DELETE", f"/api/items/{iid}")[0] == 200
    current = desk_client.req("GET", "/api/desk")[1]
    assert current["groups"][0]["item_ids"] == current["groups"][0]["items"] == []
    assert desk_client.req("PATCH", "/api/desk", {"revision": 1, "groups": [group(ids=[iid])]})[0] == 400
    assert desk_client.req("GET", "/api/desk")[1] == current


def test_group_members_are_not_truncated_to_the_browser_library_index(svc):
    """A group retains notes older than the frontend's 3,000-note index cap."""
    ids = [f"note{i:05d}" for i in range(3001)]
    svc.conn.executemany(
        "INSERT INTO knowledge_items(id,kind,title,body,provenance,created_at,updated_at)"
        " VALUES (?,'note',?,'Knowledge','stated','2026-01-01','2026-01-01')",
        [(iid, f"Saved knowledge {i}") for i, iid in enumerate(ids)])
    saved = desk.replace(svc.conn, {"revision": 0, "groups": [group(ids=ids)]})
    assert saved["groups"][0]["item_ids"] == ids
    assert len(saved["groups"][0]["items"]) == 3001
    assert saved["groups"][0]["items"][-1]["title"] == "Saved knowledge 3000"


def test_reprocessing_preserves_groups_membership_order_and_focus(svc):
    """Read again replaces generated row IDs without losing the user's contexts."""
    sid = knowledge.save_source(svc.conn, url="https://example.test/note", title="Source",
                                author=None, platform="web", content_type="web",
                                blob_sha256=None, text_sha256="hash", extractor="test")
    (old,) = knowledge.save_items(svc.conn, sid, [Candidate(kind="note", title="Version one", body="A")], "test", [])
    other = note(svc, "Keep this note first")
    desk.replace(svc.conn, {"revision": 0, "groups": [
        group(ids=[other, old], focused=True), group("second", [old])]})
    # The new canonical note wins even when a summary candidate comes first.
    summary, replacement = knowledge.save_items(svc.conn, sid, [
        Candidate(kind="summary", title="Summary", body="Summary"),
        Candidate(kind="note", title="Version two", body="Updated")], "test", [])
    current = desk.read(svc.conn)
    assert current["revision"] == 2
    assert current["groups"][0]["item_ids"] == [other, replacement]
    assert current["groups"][0]["focused"] is True
    assert current["groups"][1]["item_ids"] == [replacement]
    assert current["groups"][1]["items"][0]["title"] == "Version two"
    assert summary not in current["groups"][0]["item_ids"]
    with pytest.raises(desk.ConflictError):
        desk.replace(svc.conn, {"revision": 1, "groups": []})
    # If extraction no longer produces a note, remove unavailable memberships.
    knowledge.save_items(svc.conn, sid, [], "test", [])
    assert desk.read(svc.conn)["groups"][0]["item_ids"] == [other]


def test_desk_http_auth_csrf_methods_and_invalid_body(desk_server, desk_client):
    """The new endpoint obeys the same security boundaries as every product API."""
    assert Client(desk_server).req("GET", "/api/desk")[0] == 401
    cookie = Client(desk_server, "desk-test-token", cookie=True)
    body = {"revision": 0, "groups": []}
    assert cookie.req("PATCH", "/api/desk", body)[0] == 403
    assert cookie.req("PATCH", "/api/desk", body, headers={"Origin": "http://foreign.example"})[0] == 403
    assert cookie.req("PATCH", "/api/desk", body,
                      headers={"Origin": f"http://127.0.0.1:{cookie.port}"})[0] == 200
    assert desk_client.req("POST", "/api/desk", body)[0] == 405
    assert desk_client.req("PATCH", "/api/desk", [])[0] == 400
