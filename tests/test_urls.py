import pytest

from infoparser.domain.urls import canonicalize_url, detect_platform

CANON = "https://example.com/a/b?x=1"


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/a/b?x=1",
        "http://example.com/a/b?x=1",
        "HTTPS://Example.COM/a/b/?x=1",
        "https://www.example.com/a/b?x=1",
        "https://m.example.com/a/b?x=1",
        "https://example.com/a/b/?utm_source=tw&utm_medium=x&x=1",
        "https://example.com/a/b?x=1&fbclid=abc&igshid=1&si=2&gclid=3#frag",
    ],
)
def test_canonicalize_variants_equal(url):
    assert canonicalize_url(url) == CANON


def test_youtube_variants_equal():
    want = "https://youtube.com/watch?v=abc123"
    for u in [
        "https://youtu.be/abc123",
        "http://youtu.be/abc123?si=zzz",
        "https://www.youtube.com/watch?v=abc123&utm_source=x",
        "https://m.youtube.com/watch?v=abc123",
    ]:
        assert canonicalize_url(u) == want


def test_query_sorted_and_root_slash():
    assert canonicalize_url("https://a.com/?b=2&a=1") == "https://a.com?a=1&b=2"
    assert canonicalize_url("https://a.com/") == "https://a.com"


def test_detect_platform():
    assert detect_platform("https://www.instagram.com/p/x") == "instagram"
    assert detect_platform("https://youtu.be/x") == "youtube"
    assert detect_platform("https://vm.tiktok.com/x") == "tiktok"
    assert detect_platform("https://old.reddit.com/r/x") == "reddit"
    assert detect_platform("https://x.com/a") == "twitter"
    assert detect_platform("https://github.com/a") == "github"
    assert detect_platform("https://example.com") == "web"
    assert detect_platform(None) == "unknown"
    assert detect_platform("not a url") == "unknown"
