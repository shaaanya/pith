"""Milestone 1 end to end: submit, drain, search."""
from pith.retrieval.search import search


def test_e2e_m1(svc, drain):
    """Text and file items process, empty needs clarification, search finds both."""
    a = svc.inbox.submit(
        adapter="t", text="Sourdough starter needs regular feeding with flour and water.").id
    b = svc.inbox.submit(
        adapter="t", file=b"Kubernetes pods are scheduled onto nodes.\n", filename="k.md").id
    c = svc.inbox.submit(adapter="t", text="").id
    drain(svc)
    st = {i: svc.inbox.get(i)["status"] for i in (a, b, c)}
    assert st[a] == "processed" and st[b] == "processed"
    assert st[c] in ("failed", "needs_clarification")
    assert svc.inbox.get(c)["error"]
    assert [h.item_id for h in search(svc, "sourdough")]
    assert [h.item_id for h in search(svc, "kubernetes")]
    open_jobs = svc.conn.execute(
        "SELECT count(*) FROM jobs WHERE state NOT IN ('done','failed')").fetchone()[0]
    assert open_jobs == 0
