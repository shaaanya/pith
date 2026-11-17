"""URL canonicalisation and platform detection."""
import pytest

from pith.domain.urls import canonicalize_url, detect_platform

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
    """Scheme, case, www/m, trailing slash, tracking params and fragment normalise away."""
    assert canonicalize_url(url) == CANON


def test_youtube_variants_equal():
    """All youtube URL shapes canonicalise to one form."""
    want = "https://youtube.com/watch?v=abc123"
    for u in [
        "https://youtu.be/abc123",
        "http://youtu.be/abc123?si=zzz",
        "https://www.youtube.com/watch?v=abc123&utm_source=x",
        "https://m.youtube.com/watch?v=abc123",
    ]:
        assert canonicalize_url(u) == want


def test_query_sorted_and_root_slash():
    """Query params are sorted; a bare root loses its slash."""
    assert canonicalize_url("https://a.com/?b=2&a=1") == "https://a.com?a=1&b=2"
    assert canonicalize_url("https://a.com/") == "https://a.com"


def test_detect_platform():
    """Platform detection from the host."""
    assert detect_platform("https://www.instagram.com/p/x") == "instagram"
    assert detect_platform("https://youtu.be/x") == "youtube"
    assert detect_platform("https://vm.tiktok.com/x") == "tiktok"
    assert detect_platform("https://old.reddit.com/r/x") == "reddit"
    assert detect_platform("https://x.com/a") == "twitter"
    assert detect_platform("https://github.com/a") == "github"
    assert detect_platform("https://example.com") == "web"
    assert detect_platform(None) == "unknown"
    assert detect_platform("not a url") == "unknown"


def test_share_tracking_params_do_not_split_social_posts():
    base = "https://instagram.com/reel/Dfxp9--iVS_"
    for u in ("https://www.instagram.com/reel/Dfxp9--iVS_/",
              "https://www.instagram.com/reel/Dfxp9--iVS_/?cplk=MTNvaWFyaHEyZ28zYQ%3D%3D",
              "https://www.instagram.com/reel/Dfxp9--iVS_/?dlrf=MTNvaWFyaHEyZ28zYQ==&igsh=abc"):
        assert canonicalize_url(u) == base
