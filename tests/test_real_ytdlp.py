"""REAL yt-dlp (+ ffmpeg) against a LOOPBACK HTTP server: no external site is contacted.

Genuine evidence that the flags Pith passes are accepted by the installed yt-dlp, that the
documented failure modes map to the documented outcomes, and that URLs are cited as submitted.
Only yt-dlp's generic extractor is exercised; YouTube/Instagram/TikTok extractors are NOT.
Transcriber/vision are scripted (whisper is not installed).
"""
import subprocess

import pytest
from realtools import Probe, Reg, Vision, make_av, needs, run
from stubs.http_fixture_server import FIXTURES, FixtureServer, Route

from pith.config import load_config
from pith.pipeline import runner
from pith.pipeline.extractors import media
from pith.pipeline.extractors.base import ExtractCtx, NeedsClarificationError
from pith.worker import Failed

pytestmark = needs("yt-dlp", "ffmpeg", "ffprobe")

PAGE = ('<html><head><meta property="og:video" content="{b}/c.mp4"><title>Clip page</title></head>'
        '<body><video src="{b}/c.mp4"></video></body></html>')
CAPTIONED = ('<html><head><title>Captioned</title></head><body><video src="{b}/c.mp4">'
             '<track kind="subtitles" srclang="en" label="English" src="{b}/c.en.vtt"></video>'
             '</body></html>')

@pytest.fixture(name="site")
def site_fixture(tmp_path):
    """Loopback server: 3 s mp4 + tone, an mp3, <video>/og:video pages, a captioned page."""
    clip = make_av(tmp_path / "c.mp4", seconds=3)
    mp3 = tmp_path / "t.mp3"
    run("ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
        "-c:a", "libmp3lame", mp3)
    routes = {"/c.mp4": Route(clip.read_bytes(), ctype="video/mp4"),
              "/t.mp3": Route(mp3.read_bytes(), ctype="audio/mpeg"),
              "/c.en.vtt": Route((FIXTURES / "sample.en.vtt").read_bytes(), ctype="text/vtt"),
              "/plain.html": Route(b"<html><body>just words, no media</body></html>"),
              "/disguised.mp4": Route(b"<html><body>this is not a video</body></html>"),
              "/private/login/disguised.mp4": Route(b"<html><body>not a video</body></html>")}
    with FixtureServer(routes) as srv:
        for name, tpl in (("/page.html", PAGE), ("/cap.html", CAPTIONED)):
            routes[name] = Route(tpl.format(b=srv.base).encode())
        yield srv

def _ctx(tmp_path, url, max_bytes=None, **reg):
    env = {"PITH_HOME": str(tmp_path / "home")}
    cfg = load_config(env=env)
    if max_bytes:
        cfg.max_fetch_bytes = max_bytes
    row = {"canonical_url": url, "blob_sha256": None, "original_filename": None,
           "payload_text": url}
    return ExtractCtx(row, None, Reg(**reg), cfg)

def test_ytdlp_version_is_recorded(record_property):
    """The installed version, for the evidence table."""
    out = subprocess.run(["yt-dlp", "--version"], capture_output=True, text=True, check=True)
    record_property("yt_dlp_version", out.stdout.strip())
    assert out.stdout.strip()[:4].isdigit()

@pytest.mark.parametrize("suffix", ["/c.mp4", "/c.mp4?utm_source=x&t=1#frag"])
def test_video_url_all_flags_accepted_and_cited_as_submitted(site, tmp_path, suffix):
    """info + subs + `-x --audio-format wav` + worst-mp4 download all run; the URL is unchanged."""
    url = site.base + suffix
    t, v = Probe(), Vision()
    ex = media.extract(_ctx(tmp_path, url, transcribe=t, describe=v))
    assert ex.url == url and ex.content_type == "video" and ex.title == "c"
    assert t.seen["probe"]["sample_rate"] == "16000"  # yt-dlp's wav went through ffmpeg 16k mono
    assert v.frames and v.frames[0][0] == b"\xff\xd8"  # `-f worst[ext=mp4]/worst` file -> frames
    assert not any("frames_error" in k for k in ex.metadata)

def test_audio_url_is_audio(site, tmp_path):
    """An mp3 URL: yt-dlp reports vcodec none, so the content type is audio."""
    ex = media.extract(_ctx(tmp_path, site.base + "/t.mp3", transcribe=Probe()))
    assert ex.content_type == "audio" and ex.url == site.base + "/t.mp3"

def test_page_with_video_tag_and_og_video(site, tmp_path):
    """The generic extractor finds the <video>/og:video media on a page; the page URL is cited."""
    ex = media.extract(_ctx(tmp_path, site.base + "/page.html", transcribe=Probe()))
    assert ex.url == site.base + "/page.html" and ex.text == "scripted transcript"

def test_caption_flags_yield_timed_text_without_a_transcriber(site, tmp_path):
    """`--write-subs --sub-langs en.*,en --sub-format vtt` fetch the <track>; no whisper needed."""
    ex = media.extract(_ctx(tmp_path, site.base + "/cap.html"))
    assert "search & ranking" in ex.text and ex.timed and ex.url == site.base + "/cap.html"

def test_redirect_is_cited_as_the_url_yt_dlp_reports(tmp_path):
    """Measured: for a 302, yt-dlp's webpage_url is the redirect TARGET, which is what gets cited
    (documented behaviour; a direct media/page URL is echoed back unchanged, see above)."""
    clip = make_av(tmp_path / "c.mp4", seconds=2)
    routes = {"/c.mp4": Route(clip.read_bytes(), ctype="video/mp4"),
              "/go": Route(b"", 302, "text/plain", {"Location": "/c.mp4"})}
    with FixtureServer(routes) as srv:
        ex = media.extract(_ctx(tmp_path, srv.base + "/go", transcribe=Probe()))
    assert ex.url.endswith("/c.mp4") and not ex.url.endswith("/go")

def test_not_found_is_a_failure_with_the_http_status(svc, site):
    """404 maps to Failed (not needs_clarification), the message carries yt-dlp's 404."""
    iid = svc.inbox.submit(adapter="t", text=site.base + "/missing.mp4").id
    out = runner.process(svc, iid)
    assert isinstance(out, Failed) and "404" in out.error

def test_url_words_do_not_fake_a_login_wall(svc, site):
    """yt-dlp echoes the URL in some errors; 'login' in the URL path is not a login wall."""
    iid = svc.inbox.submit(adapter="t", text=site.base + "/private/login/disguised.mp4").id
    out = runner.process(svc, iid)
    assert isinstance(out, Failed) and "Unsupported URL" in out.error

def test_non_media_page_is_a_failure(svc, site):
    """A .mp4 URL that serves HTML with no media: yt-dlp says unsupported URL -> Failed."""
    iid = svc.inbox.submit(adapter="t", text=site.base + "/disguised.mp4").id
    out = runner.process(svc, iid)
    assert isinstance(out, Failed) and "Unsupported URL" in out.error

def test_oversize_media_asks_for_clarification_not_a_vague_failure(site, tmp_path):
    """`--max-filesize` makes yt-dlp skip the file but exit 0; that must read as 'too large'."""
    with pytest.raises(NeedsClarificationError, match="max_fetch_bytes"):
        media.extract(_ctx(tmp_path, site.base + "/c.mp4", max_bytes=1000, transcribe=Probe()))

def test_oversize_frames_video_only_costs_the_frames(site, tmp_path):
    """Captions survive when the optional frames download exceeds the cap; error recorded."""
    ex = media.extract(_ctx(tmp_path, site.base + "/cap.html", max_bytes=1000, describe=Vision()))
    assert "search & ranking" in ex.text and "max_fetch_bytes" in ex.metadata["frames_error"]


def test_url_after_double_dash_cannot_become_an_option(tmp_path):
    """A URL that looks like an option is still treated as a URL (rejected by yt-dlp, not run)."""
    marker = tmp_path / "pwned"
    with pytest.raises((RuntimeError, NeedsClarificationError)):
        media.extract(_ctx(tmp_path, f"--exec=touch {marker}", transcribe=Probe()))
    assert not marker.exists()
