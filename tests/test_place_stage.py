"""The place stage: after save, non-fatal, never over a user's own move."""
import json

from pith.pipeline import runner
from pith.providers.heuristic import HeuristicBackend
from pith.providers.ports import Capabilities, GenResult, ProviderError
from pith.providers.registry import Registry
from pith.store import shelves

TEXT = ("Dana noted that the tool called pgbouncer pools connections and cut idle sessions from "
        "400 to 60 in the staging test. The team agreed to roll pgbouncer out to production. ") * 3
NOTE_REPLY = {"context": "Infra notes.", "gaps": [], "entities": [],
              "units": [{"type": "fact", "text": "pgbouncer pools connections and cut idle "
                                                 "sessions from 400 to 60 in the staging test"}]}


class Model:
    locality, type, name = "local", "fake", "f"
    capabilities = Capabilities(text=True, context_window=8192)

    def __init__(self, placement="try | a tool to try", boom=False, reply=None):
        self.placement, self.boom, self.reply = placement, boom, reply or NOTE_REPLY

    def generate(self, messages, *, json_schema=None, max_tokens=None):
        if "You file saved notes" in messages[0]["content"]:
            if self.boom:
                raise ProviderError("down")
            return GenResult(self.placement, "m", "f")
        return GenResult(json.dumps(self.reply), "m", "f")


def with_model(svc, model, allow_remote=False):
    h = HeuristicBackend()
    h.type = "heuristic"
    svc.registry = Registry({"f": model, "heuristic": h}, {}, {"distill": ["f"]}, allow_remote)


def note_row(svc):
    return svc.conn.execute("SELECT * FROM knowledge_items WHERE kind='note'"
                            " AND deleted_at IS NULL").fetchone()


def test_model_placement_is_stored_with_an_event(svc):
    with_model(svc, Model())
    iid = svc.inbox.submit(adapter="cli", text=TEXT).id
    runner.process(svc, iid)
    r = note_row(svc)
    assert (r["shelf_id"], r["placement_by"], r["placement_why"]) == ("try", "model", "a tool to try")
    assert r["placement_model"] == "f:m"
    ev = svc.conn.execute("SELECT status FROM processing_events WHERE inbox_id=? AND stage='place'",
                          (iid,)).fetchall()
    assert [e[0] for e in ev] == ["info"]


def test_failed_model_still_saves_and_places_by_rules(svc):
    with_model(svc, Model(boom=True))
    iid = svc.inbox.submit(adapter="cli", text=TEXT, user_context="a film to watch").id
    runner.process(svc, iid)
    assert svc.inbox.get(iid)["status"] != "failed"
    r = note_row(svc)
    assert (r["shelf_id"], r["placement_by"]) == ("watch", "rule")


def test_no_model_backend_places_by_rules(svc):
    iid = svc.inbox.submit(adapter="cli", text=TEXT).id
    runner.process(svc, iid)
    r = svc.conn.execute("SELECT * FROM knowledge_items WHERE kind IN ('note','summary')"
                         " AND deleted_at IS NULL").fetchone()
    assert r["shelf_id"] in ("reference", "other") and r["placement_by"] == "default"


def test_user_move_survives_reprocess_and_place_command(svc):
    with_model(svc, Model())
    iid = svc.inbox.submit(adapter="cli", text=TEXT).id
    runner.process(svc, iid)
    shelves.set_placement(svc.conn, note_row(svc)["id"], "read", "user", "You put it here")
    svc.inbox.retry(iid)
    runner.process(svc, iid)
    r = note_row(svc)
    assert (r["shelf_id"], r["placement_by"]) == ("read", "user")
    assert runner.place_items(svc, iid, [r["id"]]) == 0
    assert note_row(svc)["shelf_id"] == "read"


def test_model_is_not_called_inside_a_write_transaction(svc):
    seen = []

    class Watching(Model):
        def generate(self, messages, **kw):
            if "You file saved notes" in messages[0]["content"]:
                seen.append(svc.conn.in_transaction)
            return super().generate(messages, **kw)

    with_model(svc, Watching())
    runner.process(svc, svc.inbox.submit(adapter="cli", text=TEXT).id)
    assert seen == [False]


def test_short_notes_never_leave_the_machine_for_placement(svc):
    class Remote(Model):
        locality = "remote"

    m = Remote()
    sent = []
    orig = m.generate
    m.generate = lambda messages, **kw: (sent.append(messages[0]["content"]), orig(messages, **kw))[1]
    with_model(svc, m, allow_remote=True)
    iid = svc.inbox.submit(adapter="cli", text="Dentist Thu 3pm, bring insurance card.").id
    runner.process(svc, iid)
    assert not any("You file saved notes" in x for x in sent)
    r = svc.conn.execute("SELECT * FROM knowledge_items WHERE kind='note'").fetchone()
    assert r["extracted_by"] == "verbatim" and r["placement_by"] in ("rule", "default")


FILMS = ("A reel about films. Paper Moon Harbor is a quiet drama about a ferry crew. "
         "The Long Dissolve came out in 2021. ") * 8


def test_resource_units_become_entries_that_keep_done_marks_across_reprocess(svc):
    from pith.store import entries
    reply = {"context": "Films.", "gaps": [], "entities": [],
             "units": [{"type": "resource", "text": "Paper Moon Harbor is a quiet drama about a ferry crew"},
                       {"type": "resource", "text": "The Long Dissolve came out in 2021"},
                       {"type": "fact", "text": "Both are mentioned in the reel"}]}
    with_model(svc, Model(reply=reply))
    iid = svc.inbox.submit(adapter="cli", text=FILMS).id
    runner.process(svc, iid)
    got = entries.for_item(svc.conn, note_row(svc)["id"])
    assert [e["text"] for e in got] == ["Paper Moon Harbor is a quiet drama about a ferry crew",
                                        "The Long Dissolve came out in 2021"]
    entries.set_done(svc.conn, got[0]["id"], True)
    svc.inbox.retry(iid)
    runner.process(svc, iid)
    again = entries.for_item(svc.conn, note_row(svc)["id"])
    assert [e["id"] for e in again] == [e["id"] for e in got] and again[0]["done_at"]


def test_backfill_places_and_syncs_entries_for_notes_saved_before_the_upgrade(svc):
    from pith.store import entries
    reply = {"context": "Films.", "gaps": [], "entities": [],
             "units": [{"type": "resource", "text": "Paper Moon Harbor is a quiet drama about a ferry crew"},
                       {"type": "fact", "text": "It is mentioned in the reel"}]}
    with_model(svc, Model(reply=reply))
    iid = svc.inbox.submit(adapter="cli", text=FILMS, user_context="watch these films").id
    runner.process(svc, iid)
    nid = note_row(svc)["id"]
    # what pre-006 data looks like: no placement, no entries
    svc.conn.execute("UPDATE knowledge_items SET shelf_id=NULL, placement_by=NULL, placement_why=NULL")
    svc.conn.execute("DELETE FROM entries")
    assert runner.backfill(svc) == 1
    row = note_row(svc)
    assert row["shelf_id"] == "watch" and row["placement_by"] == "rule"
    assert [e["text"] for e in entries.for_item(svc.conn, nid)] == [
        "Paper Moon Harbor is a quiet drama about a ferry crew"]
    assert runner.backfill(svc) == 0  # idempotent: nothing left to do
