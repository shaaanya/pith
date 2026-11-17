"""Segment embeddings die with the text they encode; reprocessing never leaves a stale vector."""

import numpy as np
from stubs.http_fixture_server import FixtureServer, Route

from pith.domain.models import SegmentIn
from pith.pipeline import runner
from pith.retrieval import index, vectors
from pith.retrieval.search import search
from pith.store import knowledge
from pith.worker import Processed

PAGE = (
    "<html><head><title>{t}</title></head><body><article><h1>{t}</h1><p>{p}</p></article>"
    "</body></html>"
)
OLD = "Zebras graze on the savanna and their stripes confuse predators. " * 6
NEW = "Quokkas hop around Rottnest Island and smile for tourists with ease. " * 6


def _page(text):
    return Route(PAGE.format(t="Animals", p=text).encode())


def _segment_vectors(svc):
    ids, mat = vectors.load(svc.conn, "test-embed-1", "segment")
    return dict(zip(ids, mat))


def test_changed_and_removed_segments_lose_their_vectors(svc, use_embedder):
    """save_segments drops the embeddings of changed and gone segments, keeps unchanged ones."""
    use_embedder(svc)
    src = knowledge.save_source(svc.conn, url=None, title="t", author=None, platform=None,
                                content_type="note", blob_sha256=None, text_sha256="x",
                                extractor="note")
    ids = knowledge.save_segments(svc.conn, src, [SegmentIn(0, "alpha", None),
                                                  SegmentIn(1, "beta", None),
                                                  SegmentIn(2, "gamma", None)])
    assert index.embed_pending(svc) >= 3
    knowledge.save_segments(svc.conn, src, [SegmentIn(0, "alpha", None),
                                            SegmentIn(1, "beta changed", None)])
    left = {int(i) for i in _segment_vectors(svc)}
    assert left == {ids[0]}  # unchanged kept; changed (1) and removed (2) dropped
    assert index.embed_pending(svc) >= 1  # the changed one is refilled
    assert {int(i) for i in _segment_vectors(svc)} == {ids[0], ids[1]}


def test_reprocess_with_different_text_never_cites_the_old_text(svc, use_embedder):
    """After a page changes, vectors encode the new text and search/ask cite only the new text."""
    emb = use_embedder(svc)
    routes = {"/a": _page(OLD)}
    with FixtureServer(routes) as srv:
        iid = svc.inbox.submit(adapter="t", text=srv.base + "/a").id
        assert isinstance(runner.process(svc, iid), Processed)
        assert _segment_vectors(svc)
        routes["/a"] = _page(NEW)
        assert isinstance(runner.process(svc, iid), Processed)
    texts = {str(r["id"]): r["text"] for r in svc.conn.execute("SELECT id, text FROM segments")}
    assert all("Zebras" not in t for t in texts.values())
    vecs = _segment_vectors(svc)
    assert set(vecs) == set(texts)  # no orphan rows, none missing
    for sid, vec in vecs.items():
        want = np.asarray(emb.embed([texts[sid]]).vectors[0], dtype=np.float32)
        assert np.allclose(vec, want / np.linalg.norm(want), atol=1e-6)
    hits = search(svc, "zebras stripes predators", mode="hybrid")
    assert all("Zebras" not in (h.text or h.snippet or "") for h in hits)
    assert not search(svc, "zebras", mode="fts")
