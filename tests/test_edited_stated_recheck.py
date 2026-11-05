"""A user-edited `stated` item must not keep a quote the cited segment no longer contains."""
from infoparser.domain.models import Candidate, SegmentIn
from infoparser.pipeline import provenance, runner
from infoparser.store import knowledge

OLD = "The bridge opened in 1901 after four years of construction by local masons."
NEW = "The museum holds pottery and textiles gathered from many regional excavations."


def _first_stated(svc, iid):
    sid = svc.inbox.get(iid)["source_id"]
    return knowledge.get_item(svc.conn, svc.conn.execute(
        "SELECT id FROM knowledge_items WHERE source_id=? AND provenance='stated'"
        " AND deleted_at IS NULL", (sid,)).fetchone()[0])


def _reprocess_with(svc, iid, monkeypatch, text):
    monkeypatch.setattr(runner, "_pieces", lambda ex: [(text, None)])
    runner.process(svc, iid)


def _setup(svc):
    iid = svc.inbox.submit(adapter="t", text=OLD).id
    runner.process(svc, iid)
    item = _first_stated(svc, iid)
    knowledge.update_item(svc.conn, item["id"], title="my edited title")
    return iid, item["id"]


def test_edited_stated_item_is_downgraded_when_its_quote_is_gone(svc, monkeypatch):
    """Reviewer probe: the page changed, the edited item must not present the old sentence."""
    iid, item_id = _setup(svc)
    _reprocess_with(svc, iid, monkeypatch, NEW)
    it = knowledge.get_item(svc.conn, item_id)
    assert it["user_edited"] == 1 and it["title"] == "my edited title"
    assert it["provenance"] == "inferred" and it["flagged"] == 1
    assert "evidence" not in it["data"] and "bridge" in it["data"]["claimed_evidence"]
    assert it["data"]["flag"] == "evidence_not_found"


def test_edited_stated_item_keeps_its_evidence_when_the_quote_still_holds(svc, monkeypatch):
    """Same page, reprocessed: nothing changes for the edited item."""
    iid, item_id = _setup(svc)
    before = knowledge.get_item(svc.conn, item_id)
    _reprocess_with(svc, iid, monkeypatch, OLD)
    after = knowledge.get_item(svc.conn, item_id)
    assert after["provenance"] == "stated" and after["data"] == before["data"]


def test_edited_stated_item_is_repointed_when_the_quote_moved(svc, monkeypatch):
    """The quote now sits in another segment: the citation follows it."""
    iid, item_id = _setup(svc)
    monkeypatch.setattr(runner, "_pieces", lambda ex: [(NEW, None), (OLD, None)])
    runner.process(svc, iid)
    it = knowledge.get_item(svc.conn, item_id)
    seg = svc.conn.execute("SELECT text FROM segments WHERE id=?",
                           (it["segment_refs"][0],)).fetchone()[0]
    assert it["provenance"] == "stated" and "bridge" in seg


def test_downgraded_fabricated_quote_is_not_stored_as_evidence():
    """C-M2: a quote the source does not contain is kept as `claimed_evidence`, never `evidence`,
    so export, the dashboard and `show` cannot present it as a source quote."""
    fake = Candidate(kind="insight", title="t", body="b", provenance="stated", confidence=0.5,
                     evidence="The bridge was demolished in 1950 by the council", segment_idx=0)
    out = provenance.check([fake], [SegmentIn(0, OLD, None)])[0]
    assert out.provenance == "inferred" and out.evidence is None
    assert out.data["claimed_evidence"].startswith("The bridge was demolished")
