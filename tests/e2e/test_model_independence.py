"""Same pipeline, interchangeable backends. Asserts the structural contract, not wording."""
from stubs.http_fixture_server import FIXTURES, FixtureServer, Route

from infoparser.providers.registry import Registry
from infoparser.retrieval import index
from infoparser.retrieval.search import search
from infoparser.services import build

from .conftest import (check_contract, cfg_for, db, drain, run_workflow, submit_notes,
                       submit_scenario)

VARIANTS = ["heuristic", "openai_compat", "cli"]
LIVE_ITEMS = "SELECT extracted_by FROM knowledge_items WHERE deleted_at IS NULL"


def _run(variant, tmp_path, stub):
    return run_workflow(variant, tmp_path / variant, stub.base_url)


def test_matrix_same_shapes_differing_extractors(tmp_path, stub):
    """Identical row shapes across backends, but extracted_by names the backend that ran."""
    shapes, by = [], {}
    for v in VARIANTS:
        res = _run(v, tmp_path, stub)
        stated, downgraded, shape = check_contract(res)
        shapes.append(shape)
        if v != "heuristic":  # model output: verbatim stated item kept, fabricated one downgraded
            assert stated >= 1 and downgraded >= 1, (v, stated, downgraded)
        if v == "cli":
            assert res["answer"].mode == "answer"
        rows = db(res["svc"]).execute("SELECT extracted_by FROM knowledge_items")
        by[v] = {x["extracted_by"] for x in rows}
    assert len(set(shapes)) == 1
    assert any(b.startswith("m:") for b in by["openai_compat"])
    assert any(b.startswith("c:") for b in by["cli"])
    assert all(b.startswith("h:") for b in by["heuristic"])
    assert len({frozenset(b) for b in by.values()}) == 3


def test_heuristic_only_degrades_labelled(tmp_path, stub):
    """No model: FTS search, retrieval-only ask, and zero model requests."""
    res = _run("heuristic", tmp_path, stub)
    assert res["answer"].mode == "retrieval-only" and res["search"].mode == "fts"
    assert not stub.requests


def test_openai_variant_hybrid_and_answer(tmp_path, stub):
    """Stub backend gives hybrid search and a cited answer."""
    res = _run("openai_compat", tmp_path, stub)
    assert res["search"].mode == "hybrid" and res["answer"].mode == "answer"
    assert {p for p, _, _ in stub.requests} >= {"/v1/chat/completions", "/v1/embeddings"}


def test_swap_chain_midway_keeps_data(tmp_path, stub):
    """Swap model chain to heuristic and reprocess: sources kept, old items versioned."""
    home = tmp_path / "swap"
    svc = build(cfg_for("openai_compat", home, stub.base_url))
    routes = {"/article": Route(FIXTURES / "article.html")}
    with FixtureServer(routes) as srv:  # stays up: reprocess re-fetches
        ids = submit_scenario(svc, srv.base)
        before = [r["id"] for r in db(svc).execute(
            "SELECT id FROM knowledge_items WHERE deleted_at IS NULL")]
        src_before = db(svc).execute("SELECT count(*) FROM sources").fetchone()[0]
        db(svc).close()
        svc = build(cfg_for("heuristic", home))  # swap the configured chain
        for i in ids:
            svc.inbox.retry(i)
        drain(svc)
    conn = db(svc)
    assert conn.execute("SELECT count(*) FROM sources").fetchone()[0] == src_before
    assert all(svc.inbox.get(i)["status"] == "processed" for i in ids)
    live = conn.execute(LIVE_ITEMS).fetchall()
    assert live and all(r[0].startswith("h:") for r in live)
    marks = ",".join("?" * len(before))
    gone = conn.execute(
        f"SELECT count(*) FROM knowledge_items WHERE id IN ({marks}) AND deleted_at IS NOT NULL",
        before).fetchone()[0]
    assert gone == len(before)
    assert conn.execute("SELECT count(*) FROM knowledge_versions").fetchone()[0] >= len(before)
    assert search(svc, "vector search")


def test_all_model_backends_removed_still_ingests_and_searches(tmp_path):
    """Nothing configured at all: ingest and search still work."""
    cfg = cfg_for("heuristic", tmp_path / "bare")
    cfg.backends, cfg.tasks = {}, {}
    svc = build(cfg)
    ids = submit_notes(svc)
    assert all(svc.inbox.get(i)["status"] == "processed" for i in ids)
    live = db(svc).execute(LIVE_ITEMS).fetchall()  # implicit heuristic backend carries its own name
    assert live and all(r[0] == "heuristic:heuristic" for r in live)
    assert search(svc, "fusion")


def test_embedding_model_switch_reindexes(tmp_path, stub):
    """Changing embed_model leaves old vectors ignored until reindex rebuilds them."""
    svc = _run("openai_compat", tmp_path, stub)["svc"]

    def models():
        return {x[0] for x in db(svc).execute("SELECT DISTINCT model_id FROM embeddings")}

    assert models() == {"m:stub-embed"}
    svc.cfg.backends["m"] = {**svc.cfg.backends["m"], "embed_model": "stub-embed-2"}
    svc.registry = Registry.from_config(svc.cfg)
    assert index.reindex(svc) > 0
    assert models() == {"m:stub-embed", "m:stub-embed-2"}
    assert search(svc, "vector search")
    index.reindex(svc, prune_old=True)
    assert models() == {"m:stub-embed-2"}
