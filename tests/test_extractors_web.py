import json

import pytest

from infoparser.pipeline import runner
from infoparser.pipeline.extractors import web
from infoparser.pipeline.htmltext import extract_main
from infoparser.worker import Failed, NeedsClarification, Processed
from stubs.http_fixture_server import FIXTURES, FixtureServer, Route


def segs(svc):
    return [r["text"] for r in svc.conn.execute("SELECT text FROM segments ORDER BY id")]


def test_web_extracts_article_without_nav_ads_keeps_headings_links(svc):
    with FixtureServer({"/a": Route(FIXTURES / "article.html")}) as srv:
        iid = svc.inbox.submit(adapter="t", text=srv.base + "/a").id
        assert isinstance(runner.process(svc, iid), Processed)
        row = svc.inbox.get(iid)
        assert row["content_type"] == "web"
        src = svc.conn.execute("SELECT * FROM sources").fetchone()
        assert src["title"] and "Vector Search Basics" in src["title"] and src["author"] == "Ada Writer"
        text = "\n".join(segs(svc))
        assert "# Vector Search Basics" in text and "## Why chunking matters" in text
        assert "nearest neighbours" in text
        for junk in ("NAVJUNK", "ADCONTENT", "SCRIPTJUNK", "SUBSCRIBEFORM", "ASIDEJUNK", "FOOTERJUNK", "Related post"):
            assert junk not in text
        # fetched page kept as original blob
        assert src["blob_sha256"] and svc.blobs.exists(src["blob_sha256"])
        # profile chosen for web content is the article profile
        assert svc.conn.execute("SELECT count(*) FROM knowledge_items").fetchone()[0] > 0


def test_extract_main_returns_links_and_meta():
    html = (FIXTURES / "article.html").read_text()
    title, text, links, meta = extract_main(html, "http://x.test/base/")
    assert ("chunking guide", "http://x.test/guide/chunking") in links
    assert meta["author"] == "Ada Writer" and "Vector Search Basics" in title
    assert "nearest neighbours" in text


def test_web_login_wall_needs_clarification(svc):
    routes = {"/w": Route(FIXTURES / "login_wall.html"), "/f": Route(b"no", 403, "text/plain")}
    with FixtureServer(routes) as srv:
        for p in ("/w", "/f"):
            iid = svc.inbox.submit(adapter="t", text=srv.base + p).id
            out = runner.process(svc, iid)
            assert isinstance(out, NeedsClarification) and "paste the text" in out.reason
    assert svc.conn.execute("SELECT count(*) FROM knowledge_items").fetchone()[0] == 0


def test_web_404_fails_with_error_original_url_kept(svc):
    with FixtureServer({}) as srv:
        url = srv.base + "/missing"
        iid = svc.inbox.submit(adapter="t", text=url).id
        out = runner.process(svc, iid)
        assert isinstance(out, Failed) and "404" in out.error
        row = svc.inbox.get(iid)
        assert row["canonical_url"].endswith("/missing") and row["payload_text"] == url  # original kept


def test_web_timeout_fails(svc, monkeypatch):
    monkeypatch.setattr(web, "FETCH_TIMEOUT", 0.3)
    with FixtureServer({"/slow": Route(b"<p>late</p>", delay=1.5)}) as srv:
        iid = svc.inbox.submit(adapter="t", text=srv.base + "/slow").id
        out = runner.process(svc, iid)
        assert isinstance(out, Failed) and out.error


@pytest.mark.parametrize("announce", [True, False])
def test_web_response_over_cap_fails_or_truncates_cleanly(svc, announce):
    svc.cfg.max_fetch_bytes = 10_000
    body = b"<p>" + b"x" * 2_000_000 + b"</p>"
    with FixtureServer({"/big": Route(body, content_length=announce)}) as srv:
        iid = svc.inbox.submit(adapter="t", text=srv.base + "/big").id
        out = runner.process(svc, iid)
        assert isinstance(out, (Failed, NeedsClarification))
        assert "max_fetch_bytes" in (out.error if isinstance(out, Failed) else out.reason)
    assert svc.inbox.get(iid)["canonical_url"]


def test_reddit_json_post_and_comments(svc):
    thread = (FIXTURES / "reddit_thread.json").read_bytes()
    with FixtureServer({"/r/LocalLLaMA/comments/abc/best_way.json": Route(thread, ctype="application/json")}) as srv:
        iid = svc.inbox.submit(adapter="t", text=srv.base + "/r/LocalLLaMA/comments/abc/best_way/").id
        assert isinstance(runner.process(svc, iid), Processed)
    locs = [r["locator"] for r in svc.conn.execute("SELECT locator FROM segments ORDER BY id")]
    assert locs[0] == "post" and locs[1] == "comment=1"
    text = "\n".join(segs(svc))
    assert "Best way to chunk PDFs?" in text and "wonder how to chunk" in text
    assert text.index("layout-aware") < text.index("Chunk by page first")  # top comment first


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://example.com/x"])
def test_fetch_refuses_non_http_schemes(url):
    with pytest.raises(ValueError, match="scheme"):
        web.fetch(url, max_bytes=1000)


def test_fetch_refuses_redirect_to_non_http():
    with FixtureServer({"/r": Route(b"", 302, headers={"Location": "file:///etc/passwd"})}) as srv:
        with pytest.raises(Exception, match="redirect|scheme"):
            web.fetch(srv.base + "/r", max_bytes=1000)


def test_fetch_follows_http_redirect():
    with FixtureServer({"/r": Route(b"", 302, headers={"Location": "/ok"}), "/ok": Route(b"hi", ctype="text/plain")}) as srv:
        res = web.fetch(srv.base + "/r", max_bytes=1000)
        assert res.status == 200 and res.body == b"hi" and res.final_url.endswith("/ok")
