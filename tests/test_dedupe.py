from stubs.hash_embedder import HashEmbedder
from infoparser.domain.models import Candidate
from infoparser.pipeline import dedupe, runner
from infoparser.retrieval import index
from infoparser.store import knowledge
from infoparser.worker import Processed
from stubs.http_fixture_server import FIXTURES, FixtureServer, Route

LONG = ("Vector databases store embeddings and support approximate nearest neighbour search over large "
        "collections of chunked documents for retrieval augmented generation pipelines in production. ")


def mk(svc, tag, cands):
    sid = knowledge.save_source(svc.conn, url=None, title=tag, author=None, platform=None, content_type="note",
                                blob_sha256=None, text_sha256=tag, extractor="note")
    return knowledge.save_items(svc.conn, sid, cands, "test", [])


def rels(svc):
    return [tuple(r) for r in svc.conn.execute("SELECT item_a, item_b, type FROM relations")]


def test_near_duplicate_detected_without_embeddings(svc):
    a = mk(svc, "s1", [Candidate("insight", "Vector DBs", LONG)])
    b = mk(svc, "s2", [Candidate("insight", "Vector DBs", LONG.replace("production", "prod"))])
    c = mk(svc, "s3", [Candidate("insight", "Cooking", "Boil the pasta in salted water for ten minutes then drain.")])
    got = dedupe.find_near_duplicates(svc.conn, b + c, svc)
    assert [(x, y) for x, y, _ in got] == [(min(a[0], b[0]), max(a[0], b[0]))] and got[0][2] >= 0.8
    assert [r[2] for r in rels(svc)] == ["duplicate"]


def test_related_items_created(svc, use_embedder):
    use_embedder(svc, HashEmbedder())
    a = mk(svc, "s1", [Candidate("insight", "Vector search", "vector search finds nearest neighbours of embeddings quickly")])
    b = mk(svc, "s2", [Candidate("insight", "Vector search", "vector search finds nearest neighbours of embeddings using indexes graphs")])
    z = mk(svc, "s3", [Candidate("insight", "Pasta", "boil water add salt cook noodles drain serve sauce")])
    index.embed_pending(svc)
    got = dedupe.find_near_duplicates(svc.conn, b + z, svc, threshold=0.99)
    assert [r[2] for r in rels(svc)] == ["related"]
    assert {x for x, y, _ in got} | {y for x, y, _ in got} == {a[0], b[0]}
    # at a lower duplicate threshold the same pair is a duplicate
    dedupe.find_near_duplicates(svc.conn, b, svc, threshold=0.5)
    assert ("duplicate" in [r[2] for r in rels(svc)])


def test_same_text_from_two_urls_one_source_two_provenance_rows(svc):
    page = (FIXTURES / "article.html")
    with FixtureServer({"/one": Route(page), "/two": Route(page)}) as srv:
        i1 = svc.inbox.submit(adapter="t", text=srv.base + "/one").id
        i2 = svc.inbox.submit(adapter="t", text=srv.base + "/two").id
        assert isinstance(runner.process(svc, i1), Processed)
        items = svc.conn.execute("SELECT count(*) FROM knowledge_items").fetchone()[0]
        assert isinstance(runner.process(svc, i2), Processed)
    assert svc.conn.execute("SELECT count(*) FROM sources").fetchone()[0] == 1
    assert svc.conn.execute("SELECT count(*) FROM knowledge_items").fetchone()[0] == items
    sid = svc.inbox.get(i1)["source_id"]
    assert svc.inbox.get(i2)["source_id"] == sid
    rows = svc.conn.execute("SELECT inbox_id, url FROM provenance_log WHERE source_id=?", (sid,)).fetchall()
    assert {r["inbox_id"] for r in rows} == {i1, i2} and len(rows) == 2
    ev = svc.conn.execute("SELECT stage FROM processing_events WHERE inbox_id=?", (i2,)).fetchall()
    assert "duplicate" in [e[0] for e in ev]


def test_dedupe_failure_never_fails_item(svc, monkeypatch):
    monkeypatch.setattr(dedupe, "find_near_duplicates", lambda *a, **k: 1 / 0)
    iid = svc.inbox.submit(adapter="t", text=LONG).id
    assert isinstance(runner.process(svc, iid), Processed)
    assert svc.conn.execute("SELECT count(*) FROM processing_events WHERE inbox_id=? AND stage='dedupe'"
                            " AND status='error'", (iid,)).fetchone()[0] == 1


def test_duplicate_replaces_related_and_related_never_overwrites_duplicate(svc, use_embedder):
    use_embedder(svc, HashEmbedder())
    a = mk(svc, "s1", [Candidate("insight", "Vector search", "vector search finds nearest neighbours of embeddings quickly")])
    b = mk(svc, "s2", [Candidate("insight", "Vector search", "vector search finds nearest neighbours of embeddings using indexes graphs")])
    index.embed_pending(svc)
    dedupe.find_near_duplicates(svc.conn, b, svc, threshold=0.99)
    assert [r[2] for r in rels(svc)] == ["related"]
    dedupe.find_near_duplicates(svc.conn, b, svc, threshold=0.5)
    assert [r[2] for r in rels(svc)] == ["duplicate"]
    dedupe.find_near_duplicates(svc.conn, b, svc, threshold=0.99)
    assert [r[2] for r in rels(svc)] == ["duplicate"]


def test_thresholds_are_named_constants():
    assert dedupe.DUPLICATE_COSINE == 0.92 and dedupe.RELATED_COSINE == 0.75 and dedupe.JACCARD == 0.8


def test_duplicate_event_names_original_inbox_and_source(svc):
    page = FIXTURES / "article.html"
    with FixtureServer({"/one": Route(page), "/two": Route(page)}) as srv:
        i1 = svc.inbox.submit(adapter="t", text=srv.base + "/one").id
        i2 = svc.inbox.submit(adapter="t", text=srv.base + "/two").id
        runner.process(svc, i1)
        runner.process(svc, i2)
    d = svc.conn.execute("SELECT detail FROM processing_events WHERE inbox_id=? AND stage='duplicate'", (i2,)).fetchone()[0]
    assert i1 in d and svc.inbox.get(i1)["source_id"] in d
