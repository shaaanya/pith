"""Shelves: seeded built-ins, custom shelf CRUD, placement and its survival across reprocess."""
import pytest

from pith.domain.models import Candidate
from pith.store import knowledge, shelves

BUILTIN_IDS = ["watch", "listen", "read", "play", "try", "visit", "reference", "other"]


def _note(conn, title="A note"):
    sid = knowledge.save_source(conn, url="http://x.test/a", title="t", author=None,
                                platform=None, content_type="web", blob_sha256=None,
                                text_sha256="h", extractor="web")
    (iid,) = knowledge.save_items(conn, sid, [Candidate(kind="note", title=title, body="b")],
                                  "m", [])
    return sid, iid


def _row(conn, iid):
    return conn.execute("SELECT * FROM knowledge_items WHERE id=?", (iid,)).fetchone()


def test_builtins_are_seeded_in_order_and_other_is_builtin(svc):
    got = shelves.list_shelves(svc.conn)
    assert [s["id"] for s in got] == BUILTIN_IDS
    assert all(s["builtin"] for s in got)
    watch = got[0]
    assert watch["name"] == "Watch" and watch["todo"] and watch["done_label"] == "Watched"
    assert not got[-1]["todo"] and got[-1]["id"] == "other"


def test_create_update_and_name_rules(svc):
    s = shelves.create_shelf(svc.conn, "Recipes to cook", "Dishes I want to make")
    assert s["id"] == "recipes-to-cook" and not s["builtin"]
    assert shelves.list_shelves(svc.conn)[-1]["id"] == "recipes-to-cook"
    assert shelves.update_shelf(svc.conn, s["id"], blurb="New")["blurb"] == "New"
    assert shelves.update_shelf(svc.conn, s["id"], name="Cook")["name"] == "Cook"
    for bad in ("", "   ", "Recipes", "Cook", "watch"):  # empty, and names already taken
        with pytest.raises(ValueError):
            shelves.create_shelf(svc.conn, bad) if bad != "Recipes" else \
                shelves.update_shelf(svc.conn, s["id"], name="Watch")
    with pytest.raises(KeyError):
        shelves.update_shelf(svc.conn, "nope", name="x")


def test_delete_custom_moves_notes_to_other_and_builtins_stay(svc):
    _, iid = _note(svc.conn)
    s = shelves.create_shelf(svc.conn, "Cooking")
    shelves.set_placement(svc.conn, iid, s["id"], "user", "You put it here")
    shelves.delete_shelf(svc.conn, s["id"])
    r = _row(svc.conn, iid)
    assert r["shelf_id"] == "other" and r["placement_by"] == "default"
    assert "deleted" in r["placement_why"]  # not a false "you put it here"
    assert s["id"] not in [x["id"] for x in shelves.list_shelves(svc.conn)]
    for b in ("other", "watch"):
        with pytest.raises(ValueError):
            shelves.delete_shelf(svc.conn, b)
    with pytest.raises(KeyError):
        shelves.delete_shelf(svc.conn, "nope")


def test_set_placement_and_placement_of(svc):
    _, iid = _note(svc.conn)
    assert shelves.placement_of(_row(svc.conn, iid)) == {"shelf": "other", "by": None, "why": None}
    shelves.set_placement(svc.conn, iid, "try", "model", "a repo", model="ollama:m")
    r = _row(svc.conn, iid)
    assert shelves.placement_of(r) == {"shelf": "try", "by": "model", "why": "a repo"}
    assert r["placement_model"] == "ollama:m" and r["placed_at"]
    with pytest.raises(KeyError):
        shelves.set_placement(svc.conn, iid, "nope", "user", "x")


def test_user_placement_survives_reprocess_but_automatic_does_not(svc):
    sid, iid = _note(svc.conn)
    shelves.set_placement(svc.conn, iid, "try", "user", "You put it here")
    (new,) = knowledge.save_items(svc.conn, sid, [Candidate(kind="note", title="v2", body="b")],
                                  "m", [])
    r = _row(svc.conn, new)
    assert (r["shelf_id"], r["placement_by"], r["placement_why"]) == ("try", "user", "You put it here")
    shelves.set_placement(svc.conn, new, "watch", "model", "a film")
    (newer,) = knowledge.save_items(svc.conn, sid, [Candidate(kind="note", title="v3", body="b")],
                                    "m", [])
    assert _row(svc.conn, newer)["shelf_id"] is None


def test_custom_shelves_are_to_do_shelves_you_can_tick_off(svc):
    s = shelves.create_shelf(svc.conn, "Recipes to cook")
    assert s["todo"] and s["done_label"] == "Done"
