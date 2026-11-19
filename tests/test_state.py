"""Per-note state and entries: stored by source so they survive reprocess."""
import pytest

from pith.domain.models import Candidate
from pith.store import entries, knowledge, state


def _note(conn, units=()):
    sid = knowledge.save_source(conn, url="http://x.test/a", title="t", author=None, platform=None,
                                content_type="web", blob_sha256=None, text_sha256="h",
                                extractor="web")
    (iid,) = knowledge.save_items(conn, sid, [Candidate(kind="note", title="N", body="b",
                                  data={"units": list(units)})], "m", [])
    return sid, iid


def test_state_defaults_and_set_roundtrip(svc):
    sid, iid = _note(svc.conn)
    assert state.owner_of(svc.conn, iid) == sid
    assert state.get(svc.conn, sid) == {"done_at": None, "snooze_until": None, "hidden": False}
    state.set_state(svc.conn, sid, done=True)
    assert state.get(svc.conn, sid)["done_at"]
    state.set_state(svc.conn, sid, snooze_until="2030-01-01T00:00:00Z", hidden=True)
    got = state.get(svc.conn, sid)
    assert got["snooze_until"] == "2030-01-01T00:00:00Z" and got["hidden"] and got["done_at"]
    state.set_state(svc.conn, sid, done=False, snooze_until=None, hidden=False)
    assert state.get(svc.conn, sid) == {"done_at": None, "snooze_until": None, "hidden": False}


def test_state_validates_snooze(svc):
    sid, _ = _note(svc.conn)
    for bad in ("tomorrow", 5, ""):
        with pytest.raises(ValueError):
            state.set_state(svc.conn, sid, snooze_until=bad)


def test_state_survives_reprocess_because_it_is_keyed_by_source(svc):
    sid, _ = _note(svc.conn)
    state.set_state(svc.conn, sid, done=True)
    (new,) = knowledge.save_items(svc.conn, sid, [Candidate(kind="note", title="v2", body="b")],
                                  "m", [])
    assert state.owner_of(svc.conn, new) == sid and state.get(svc.conn, sid)["done_at"]


def test_mark_viewed(svc):
    _, iid = _note(svc.conn)
    assert state.mark_viewed(svc.conn, iid)
    assert knowledge.get_item(svc.conn, iid)["last_viewed_at"]


def test_entries_sync_keeps_done_marks_by_text_and_drops_vanished(svc):
    sid, iid = _note(svc.conn)
    got = entries.sync(svc.conn, sid, iid, ["Paper Moon Harbor", "The Long Dissolve", "  paper   moon harbor "])
    assert [e["text"] for e in got] == ["Paper Moon Harbor", "The Long Dissolve"]  # deduped
    entries.set_done(svc.conn, got[0]["id"], True)
    (new,) = knowledge.save_items(svc.conn, sid, [Candidate(kind="note", title="v2", body="b")],
                                  "m", [])
    again = entries.sync(svc.conn, sid, new, ["the long dissolve", "Orchard Court", "Paper Moon Harbor"])
    by = {e["text"]: e for e in again}
    assert by["Paper Moon Harbor"]["done_at"] and by["Paper Moon Harbor"]["id"] == got[0]["id"]
    assert by["Orchard Court"]["done_at"] is None and "The Long Dissolve" not in by
    assert [e["id"] for e in entries.for_item(svc.conn, new)] == [e["id"] for e in again]
    assert entries.for_item(svc.conn, iid) == []  # the replaced row has none
    with pytest.raises(KeyError):
        entries.set_done(svc.conn, "nope", True)


def test_a_done_entry_survives_the_model_rewording_it_on_reprocess(svc):
    from pith.store import entries
    got = entries.sync(svc.conn, "o", "i1", ["Prisoners (2013): a missing-child thriller", "Zodiac"])
    entries.set_done(svc.conn, got[0]["id"], True)
    again = entries.sync(svc.conn, "o", "i2", ["Prisoners (2013), a missing child thriller", "Zodiac"])
    assert again[0]["id"] == got[0]["id"] and again[0]["done_at"]
    assert again[0]["text"] == "Prisoners (2013), a missing child thriller"


def test_a_done_entry_that_vanishes_entirely_is_kept_not_deleted(svc):
    from pith.store import entries
    got = entries.sync(svc.conn, "o", "i1", ["Zodiac"])
    entries.set_done(svc.conn, got[0]["id"], True)
    entries.sync(svc.conn, "o", "i1", ["Something else entirely"])
    assert any(e["text"] == "Zodiac" and e["done_at"] for e in entries.for_item(svc.conn, "i1"))
