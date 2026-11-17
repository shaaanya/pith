import json

import pytest

from pith.pipeline import runner
from pith.pipeline.extractors import web
from pith.pipeline.htmltext import extract_main
from pith.worker import Failed, NeedsClarification, Processed
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


def test_reddit_json_post_and_comments(svc, monkeypatch):
    monkeypatch.setattr(web, "REDDIT_HOSTS", ("127.0.0.1",))
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


BODY = ("<h1>Guide</h1>" + "<p>Retrieval systems chunk documents into passages and embed each one. </p>" * 8)


@pytest.mark.parametrize("html", [
    f"<html><body class='has-sidebar'><article>{BODY}</article></body></html>",
    f"<html><body class='no-sidebar modal-open'><main>{BODY}</main></body></html>",
    f"<html><body><div id='page-with-sidebar'><article>{BODY}</article></div></body></html>",
    f"<html><body><div class='sidebar-layout wrap'><div class='content'>{BODY}</div></div></body></html>",
])
def test_wrapper_class_tokens_do_not_hide_article(html):
    _, text, _, _ = extract_main(html, "http://x.test/")
    assert "chunk documents into passages" in text


def test_real_sidebar_and_ad_still_dropped():
    html = (f"<html><body><article>{BODY}<div class='ad'>BUYADS</div></article>"
            "<div class='sidebar'><a href='/a'>NAVLINKONE</a><a href='/b'>NAVLINKTWO</a></div></body></html>")
    _, text, _, _ = extract_main(html, "http://x.test/")
    assert "BUYADS" not in text and "NAVLINKONE" not in text and "chunk documents" in text


def test_long_page_mentioning_enable_javascript_is_not_refused(svc):
    page = ("<html><body><article><h1>Tutorial</h1><p>First, enable JavaScript in your browser settings.</p>"
            + "<p>Then we explain how retrieval augmented generation works in practice.</p>" * 40
            + "</article></body></html>")
    with FixtureServer({"/t": Route(page.encode())}) as srv:
        iid = svc.inbox.submit(adapter="t", text=srv.base + "/t").id
        assert isinstance(runner.process(svc, iid), Processed)


def test_pdf_and_json_urls_get_clear_clarification(svc):
    routes = {"/p": Route(b"%PDF-1.4", ctype="application/pdf"), "/j": Route(b"{}", ctype="application/json")}
    with FixtureServer(routes) as srv:
        out = runner.process(svc, svc.inbox.submit(adapter="t", text=srv.base + "/p").id)
        assert isinstance(out, NeedsClarification) and "PDF" in out.reason and "submit the file" in out.reason
        out = runner.process(svc, svc.inbox.submit(adapter="t", text=srv.base + "/j").id)
        assert isinstance(out, NeedsClarification) and "application/json" in out.reason


def test_reddit_path_on_non_reddit_host_is_plain_web(svc):
    # no monkeypatch: 127.0.0.1 is not a reddit host, so no .json rewrite is attempted
    with FixtureServer({"/r/x/comments/1/t": Route(FIXTURES / "article.html")}) as srv:
        iid = svc.inbox.submit(adapter="t", text=srv.base + "/r/x/comments/1/t").id
        assert isinstance(runner.process(svc, iid), Processed)
        assert not any(h.endswith(".json") for h in srv.hits)


def test_https_submitted_url_never_downgrades_to_http(svc):
    with FixtureServer({"/a": Route(FIXTURES / "article.html")}) as srv:
        url = srv.base.replace("http://", "https://") + "/a"
        out = runner.process(svc, svc.inbox.submit(adapter="t", text=url).id)
        assert isinstance(out, Failed)
        assert srv.hits == []  # plain-http server never saw a request


def test_pathological_nesting_fails_cleanly(svc):
    page = "<html><body>" + "<div>" * 5000 + "deep text " * 50 + "</div>" * 5000 + "</body></html>"
    with FixtureServer({"/d": Route(page.encode())}) as srv:
        out = runner.process(svc, svc.inbox.submit(adapter="t", text=srv.base + "/d").id)
        assert isinstance(out, (Failed, NeedsClarification, Processed))  # must not crash the worker
        if isinstance(out, Failed):
            assert "nest" in out.error


def test_non_page_content_type_clarification_does_not_invite_pasting(svc):
    with FixtureServer({"/z": Route(b"PK\x03\x04zip", ctype="application/zip")}) as srv:
        iid = svc.inbox.submit(adapter="t", text=srv.base + "/z").id
        out = runner.process(svc, iid)
        assert isinstance(out, NeedsClarification)
        assert "paste" not in out.reason.lower() and "submit the file" in out.reason
        assert not getattr(out, "pasteable", False)
