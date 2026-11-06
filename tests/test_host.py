import json

import pytest

from infoparser import host

DOC = ("Zebras sleep standing up because lions hunt at night. "
       "Their stripes confuse biting flies, a 2019 study found. " * 3)
GOOD = {"summary": "Zebra facts.",
        "insights": [{"text": "Zebras sleep standing", "quote": "Zebras sleep standing up because lions hunt"},
                     {"text": "Invented", "quote": "this quote is not in the document at all"}]}


@pytest.fixture(name="src")
def src_fixture(svc, drain):
    svc.inbox.submit(adapter="cli", text=DOC)
    drain(svc)
    return svc.conn.execute("SELECT id, text_sha256 FROM sources").fetchone()


def live(svc, sid):
    return svc.conn.execute("SELECT title, provenance, extracted_by FROM knowledge_items "
                            "WHERE source_id=? AND deleted_at IS NULL", (sid,)).fetchall()


def test_apply_replaces_heuristic_and_downgrades_fake_quote(svc, src):
    assert all(r["extracted_by"].startswith("heuristic") for r in live(svc, src["id"]))
    n = host.apply(svc, src["id"], src["text_sha256"], json.dumps(GOOD), "claude")
    rows = live(svc, src["id"])
    assert n == len(rows) == 3 and {r["extracted_by"] for r in rows} == {"host:claude"}
    prov = {r["title"]: r["provenance"] for r in rows}
    assert prov["Zebras sleep standing"] == "stated" and prov["Invented"] == "inferred"


def test_user_edited_item_survives(svc, src):
    keep = live(svc, src["id"])[0]["title"]
    svc.conn.execute("UPDATE knowledge_items SET user_edited=1 WHERE title=?", (keep,))
    host.apply(svc, src["id"], src["text_sha256"], json.dumps(GOOD))
    assert keep in {r["title"] for r in live(svc, src["id"])}


@pytest.mark.parametrize("sha,reply,msg", [("stale", json.dumps(GOOD), "stale"),
                                           (None, "not json at all", "not valid JSON"),
                                           (None, '{"insights": []}', "summary")])
def test_bad_apply_changes_nothing(svc, src, sha, reply, msg):
    before = live(svc, src["id"])
    with pytest.raises(host.HostError, match=msg):
        host.apply(svc, src["id"], sha or src["text_sha256"], reply)
    assert [tuple(r) for r in live(svc, src["id"])] == [tuple(r) for r in before]


def test_prompt_gated_by_privacy_and_audited(svc, src):
    with pytest.raises(host.HostError, match="allow_remote"):
        host.prompt(svc, src["id"])
    p = host.prompt(svc, src["id"], ack=True)
    assert p["text"].startswith("Zebras") and p["text_sha256"] == src["text_sha256"]
    assert "UNTRUSTED" in p["instructions"]
    assert svc.conn.execute("SELECT count(*) FROM processing_events WHERE backend='host' AND egress=1"
                            ).fetchone()[0] == 1


def test_inbox_id_accepted(svc, src):
    iid = svc.conn.execute("SELECT id FROM inbox_items").fetchone()["id"]
    assert host.prompt(svc, iid, ack=True)["source_id"] == src["id"]
    assert host.apply(svc, iid, src["text_sha256"], json.dumps(GOOD)) == 3


def test_ask_retrieval_only_never_calls_a_generator(svc, src, monkeypatch):
    from infoparser.retrieval.ask import ask
    monkeypatch.setattr(svc.registry, "generators", lambda task: pytest.fail("generator used"))
    a = ask(svc, "zebras sleep", retrieval_only=True)
    assert a.mode == "retrieval-only" and a.retrieved
