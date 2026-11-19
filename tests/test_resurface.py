"""Resurfacing: only with a stated reason, never random; honours snooze/hide/done."""
import datetime as dt

from pith import resurface
from pith.domain.models import Candidate
from pith.ids import new_id
from pith.store import knowledge, shelves, state

NOW = dt.datetime(2026, 11, 18, 9, 0, tzinfo=dt.UTC)


def note(svc, title, days, *, intent=None, shelf=None, by="rule", topics=()):
    n = [0]
    sid = knowledge.save_source(svc.conn, url=f"http://x.test/{title}", title=title, author=None,
                                platform=None, content_type="web", blob_sha256=None,
                                text_sha256=title, extractor="web")
    (iid,) = knowledge.save_items(svc.conn, sid, [Candidate(
        kind="note", title=title, body="b",
        data={"intent": {"state": "explicit" if intent else "unknown", "text": intent}})], "m", [])
    when = (NOW - dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    svc.conn.execute("UPDATE knowledge_items SET created_at=? WHERE id=?", (when, iid))
    if shelf:
        shelves.set_placement(svc.conn, iid, shelf, by, "why")
    for t in topics:
        tid = svc.conn.execute("SELECT id FROM topics WHERE name=?", (t,)).fetchone()
        tid = tid[0] if tid else new_id()
        svc.conn.execute("INSERT OR IGNORE INTO topics(id,name) VALUES (?,?)", (tid, t))
        svc.conn.execute("INSERT INTO item_topics VALUES (?,?)", (iid, tid))
    return sid, iid


def test_nothing_without_a_reason(svc):
    for i in range(5):
        note(svc, f"plain {i}", 40)
    assert resurface.resurface(svc.conn, NOW) == []


def test_open_intent_on_an_action_shelf_resurfaces_with_why_until_done(svc):
    sid, iid = note(svc, "Try fm-lite", 30, intent="try this tool", shelf="try")
    note(svc, "Fresh one", 2, intent="try this too", shelf="try")  # newer than 14 days: not offered
    got = resurface.resurface(svc.conn, NOW)
    assert [g["id"] for g in got] == [iid] and got[0]["kind"] == "intent"
    assert "try this tool" in got[0]["why"] and "haven't marked it done" in got[0]["why"]
    state.set_state(svc.conn, sid, done=True)
    assert resurface.resurface(svc.conn, NOW) == []


def test_snooze_and_hide_are_honoured(svc):
    sid, _ = note(svc, "Try fm-lite", 30, intent="try this tool", shelf="try")
    state.set_state(svc.conn, sid, snooze_until="2026-12-01T00:00:00Z")
    assert resurface.resurface(svc.conn, NOW) == []
    state.set_state(svc.conn, sid, snooze_until="2026-11-01T00:00:00Z")  # snooze has passed
    assert len(resurface.resurface(svc.conn, NOW)) == 1
    state.set_state(svc.conn, sid, hidden=True)
    assert resurface.resurface(svc.conn, NOW) == []


def test_topic_overlap_with_this_weeks_saves(svc):
    _, old = note(svc, "Old pooling notes", 40, topics=["postgres"])
    note(svc, "w1", 1, topics=["postgres"])
    note(svc, "w2", 2, topics=["postgres"])
    for i in range(30):  # a topic on most notes says nothing
        note(svc, f"filler {i}", 50, topics=["general"])
    got = resurface.resurface(svc.conn, NOW)
    assert [g["id"] for g in got] == [old] and got[0]["kind"] == "topic"
    assert "postgres" in got[0]["why"] and "2 notes" in got[0]["why"]


def test_long_waiting_on_a_shelf_needs_a_real_placement_and_caps_at_three(svc):
    note(svc, "default placed", 60, shelf="watch", by="default")
    for i in range(5):
        note(svc, f"waiting {i}", 20 + i, shelf="read", by="user")
    got = resurface.resurface(svc.conn, NOW)
    assert len(got) == 3 and all(g["kind"] == "shelf" for g in got)
    assert all("Read shelf" in g["why"] for g in got)
    assert [g["score"] for g in got] == sorted((g["score"] for g in got), reverse=True)
