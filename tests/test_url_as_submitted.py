"""The submitted URL is fetched and cited as given; the canonical form is only the dedupe key."""

import io
from contextlib import redirect_stdout

import pytest

from stubs.http_fixture_server import FIXTURES, FixtureServer, Route

from pith import cli, digest
from pith.dashboard import api
from pith.pipeline import runner
from pith.pipeline.extractors import web
from pith.retrieval import search as search_mod
from pith.worker import Processed


def _process(svc, url):
    """Submit and run the pipeline once; returns the inbox id."""
    iid = svc.inbox.submit(adapter="t", text=url).id
    assert isinstance(runner.process(svc, iid), Processed)
    return iid


def test_http_only_site_is_stored_and_cited_as_http(svc):
    """An http-only site is stored and cited as http, never rewritten to https."""
    with FixtureServer({"/a": Route(FIXTURES / "article.html")}) as srv:
        url = srv.base + "/a"
        _process(svc, url)
    assert svc.conn.execute("SELECT url FROM sources").fetchone()["url"] == url
    hits = search_mod.search(svc, "chunking", mode="fts")
    assert hits and all(h.source_url == url for h in hits)


@pytest.mark.parametrize(
    "url",
    [
        "https://www.example.org/x/?b=2&a=1&utm_source=z",
        "https://m.example.com/Path/",
        "http://www.example.net/a",
    ],
)
def test_host_path_and_query_are_fetched_as_submitted(svc, monkeypatch, url):
    """www., m., trailing slash and tracking params are fetched exactly as submitted."""
    seen = []

    def fake_fetch(u, *, max_bytes, timeout=None, untrusted=False):  # pylint: disable=unused-argument
        """Serve the article fixture for any URL."""
        seen.append(u)
        body = (FIXTURES / "article.html").read_bytes()
        return web.FetchResult(200, "text/html", body[:max_bytes], u)

    monkeypatch.setattr(web, "fetch", fake_fetch)
    _process(svc, url)
    assert seen == [url]
    assert svc.conn.execute("SELECT url FROM sources").fetchone()["url"] == url


def test_cited_url_is_the_one_after_redirects(svc):
    """The cited URL is the one that actually served the content."""
    routes = {"/old": Route(b"", 302, headers={"Location": "/new"}),
              "/new": Route(FIXTURES / "article.html")}
    with FixtureServer(routes) as srv:
        _process(svc, srv.base + "/old")
        assert svc.conn.execute("SELECT url FROM sources").fetchone()["url"] == srv.base + "/new"


def test_duplicates_still_detected_across_variants(svc):
    """The canonical key still folds tracking params, slash, www/m and http/https."""
    variants = [
        "https://www.example.org/x/?utm_source=a",
        "http://example.org/x",
        "https://m.example.org/x/",
    ]
    ids = {svc.inbox.submit(adapter="t", text=v).id for v in variants}
    assert len(ids) == 1
    row = svc.inbox.get(ids.pop())
    assert row["canonical_url"] == "https://example.org/x"
    assert row["payload_text"] == variants[0]


def test_reprocess_heals_an_old_canonical_form_row(svc):
    """Reprocessing rewrites an old https-form sources.url to the fetched one."""
    with FixtureServer({"/a": Route(FIXTURES / "article.html")}) as srv:
        url = srv.base + "/a"
        iid = _process(svc, url)
        svc.conn.execute("UPDATE sources SET url=?", ("https://" + url[len("http://"):],))
        assert isinstance(runner.process(svc, iid), Processed)
        assert svc.conn.execute("SELECT url FROM sources").fetchone()["url"] == url


def test_listings_show_the_url_as_submitted(svc):
    """Dashboard, cli and digest list the URL as submitted."""
    url = "https://www.example.org/x/?utm_source=a"
    svc.inbox.submit(adapter="t", text=url)
    assert api.inbox_list(svc, None)[0]["what"] == url
    assert api.inbox_list(svc, None)[0]["url"] == url
    out = io.StringIO()
    with redirect_stdout(out):
        cli.main(["--home", str(svc.cfg.home), "inbox"])
    assert url in out.getvalue()
    svc.conn.execute("UPDATE inbox_items SET status='failed', error='x'")
    assert digest.data(svc)["attention"][0]["what"] == url
