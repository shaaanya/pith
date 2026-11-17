"""Source -> extraction -> note -> storage -> retrieval, with a fake model backend."""
import json

from infoparser.dashboard import api
from infoparser import digest
from infoparser.pipeline import runner
from infoparser.providers.heuristic import HeuristicBackend
from infoparser.providers.ports import Capabilities, GenResult
from infoparser.providers.registry import Registry
from infoparser.retrieval.search import search

TEXT = ("Weekly infra sync. We reviewed connection limits on the primary database. "
        "Dana noted that the tool called pgbouncer pools connections and cut idle sessions from "
        "400 to 60 in the staging test. Marcus asked about failover and Dana said patroni handles "
        "promotion automatically. The team agreed to roll pgbouncer out to production on 12 March. "
        "Separately, the on call rotation changes next month and the runbook needs a refresh. ") * 2

REPLY = {"context": "Infra sync notes on database connection pooling.",
         "units": [{"type": "fact", "text": "pgbouncer pools connections and cut idle sessions "
                                            "from 400 to 60 in the staging test"},
                   {"type": "step", "text": "Roll pgbouncer out to production on 12 March"},
                   {"type": "fact", "text": "The team will triple revenue by 5000 percent"}],
         "entities": ["pgbouncer", "patroni", "Invented Inc"], "gaps": []}


class Fake:
    locality, type = "local", "fake"
    name = "f"
    capabilities = Capabilities(text=True, context_window=8192)

    def __init__(self):
        self.calls = 0

    def generate(self, messages, *, json_schema=None, max_tokens=None):
        self.calls += 1
        return GenResult(json.dumps(REPLY), "m", "f")


def with_model(svc):
    h = HeuristicBackend()
    h.type = "heuristic"
    fake = Fake()
    svc.registry = Registry({"f": fake, "heuristic": h}, {}, {"distill": ["f"]}, False)
    return fake


def kinds(svc, sid):
    return [r[0] for r in svc.conn.execute(
        "SELECT kind FROM knowledge_items WHERE source_id=? AND deleted_at IS NULL ORDER BY"
        " created_at, rowid", (sid,))]


def test_note_pipeline_end_to_end(svc):
    with_model(svc)
    iid = svc.inbox.submit(adapter="cli", text=TEXT, user_context="saved for the pgbouncer tool").id
    runner.process(svc, iid)
    sid = svc.inbox.get(iid)["source_id"]
    assert kinds(svc, sid) == ["note", "mentions", "unit", "unit"]  # fabricated unit dropped
    note = svc.conn.execute("SELECT * FROM knowledge_items WHERE kind='note'").fetchone()
    data = json.loads(note["data_json"])
    assert data["intent"] == {"state": "explicit", "text": "saved for the pgbouncer tool"}
    assert data["dropped"] == {"unsupported_number": 1}
    assert "triple revenue" not in note["body"] and "12 March" in note["body"]
    assert note["body"].startswith("**Why saved:** saved for the pgbouncer tool")
    # a brief named thing is findable even though it is not the headline
    assert any(h.kind in ("unit", "note", "mentions") for h in search(svc, "patroni"))
    names = {r[0] for r in svc.conn.execute("SELECT name FROM entities")}
    assert "patroni" in names and "invented inc" not in names
    # units point at the supporting segment; the digest lists notes, not index rows
    unit = svc.conn.execute("SELECT segment_refs FROM knowledge_items WHERE kind='unit'").fetchone()
    assert json.loads(unit["segment_refs"])
    d = digest.data(svc, since_days=1)
    assert {i["kind"] for i in d["new"]["items"]} == {"note"} and d["library_items"] == 1
    # inbox preview shows knowledge, and the detail API shows each unit's locator
    assert "pgbouncer" in api.inbox_list(svc, None)[0]["preview"]
    detail = api.item_detail(svc, note["id"])
    assert detail["note"]["units"][0]["locator"].startswith("char=")


def test_reprocess_replaces_the_note_without_duplicates(svc):
    fake = with_model(svc)
    iid = svc.inbox.submit(adapter="cli", text=TEXT).id
    runner.process(svc, iid)
    runner.process(svc, iid)
    sid = svc.inbox.get(iid)["source_id"]
    assert kinds(svc, sid).count("note") == 1 and fake.calls == 2
    assert svc.conn.execute("SELECT count(*) FROM knowledge_versions").fetchone()[0] >= 4


def test_adapter_context_is_not_taken_for_a_reason(svc):
    with_model(svc)
    iid = svc.inbox.submit(adapter="fs", text=TEXT, user_context="from sync.txt").id
    runner.process(svc, iid)
    data = json.loads(svc.conn.execute("SELECT data_json FROM knowledge_items WHERE kind='note'")
                      .fetchone()[0])
    assert data["intent"]["state"] == "unknown"


def test_without_a_model_backend_the_legacy_heuristic_still_produces_items(svc):
    iid = svc.inbox.submit(adapter="cli", text=TEXT).id
    runner.process(svc, iid)
    sid = svc.inbox.get(iid)["source_id"]
    assert kinds(svc, sid) and "note" not in kinds(svc, sid)
