"""Media URLs reach yt-dlp and the citation exactly as submitted; routing survives rewriting."""

import json
from pathlib import Path

import pytest

from pith.pipeline import runner
from pith.pipeline.detect import detect
from pith.worker import Processed

FAKE = str(Path(__file__).parent / "stubs" / "fake_ytdlp.py")


@pytest.mark.parametrize(
    "url",
    [
        "http://media.example.org/talk.mp4",
        "https://youtu.be/vid123?t=42&utm_source=x",
        "https://www.youtube.com/watch?v=vid123&utm_medium=y",
        "https://m.youtube.com/watch?v=vid123",
    ],
)
def test_ytdlp_gets_and_source_cites_the_submitted_url(svc, monkeypatch, tmp_path, url):
    """No https rewrite, no www/m stripping, no youtu.be rewrite, tracking params kept."""
    log = tmp_path / "ytdlp.log"
    monkeypatch.setenv("FAKE_YTDLP_LOG", str(log))
    monkeypatch.delenv("FAKE_YTDLP_MODE", raising=False)
    svc.cfg.yt_dlp_binary = FAKE
    iid = svc.inbox.submit(adapter="t", text=url).id
    assert isinstance(runner.process(svc, iid), Processed)
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    assert calls and all(argv[-1] == url for argv in calls)
    assert svc.conn.execute("SELECT url FROM sources").fetchone()["url"] == url


def test_variants_still_dedupe_to_one_item(svc):
    """The canonical key still folds the media URL variants."""
    a = svc.inbox.submit(adapter="t", text="https://youtu.be/vid123?t=42").id
    b = svc.inbox.submit(adapter="t", text="https://www.youtube.com/watch?v=vid123&t=42").id
    assert a == b
    c = svc.inbox.submit(adapter="t", text="https://www.youtube.com/watch?v=vid123&utm_x=1").id
    d = svc.inbox.submit(adapter="t", text="https://youtu.be/vid123").id
    assert c == d


@pytest.mark.parametrize(
    "url, kind",
    [
        ("http://example.org/talk.mp3", "audio"),
        ("http://www.example.org/clip.MP4", "video"),
        ("http://example.org/paper.pdf", "pdf"),
        ("http://www.example.org/page", "web"),
        ("https://m.youtube.com/watch?v=x", "video"),
        ("https://www.youtube.com/watch?v=x", "video"),
        ("https://youtu.be/x", "video"),
        ("https://www.instagram.com/p/abc/", "video"),
    ],
)
def test_detect_routes_by_the_submitted_form(svc, url, kind):
    """Media vs web vs pdf is decided from what was submitted, canonical form differing."""
    row = svc.inbox.get(svc.inbox.submit(adapter="t", text=url).id)
    assert row["canonical_url"] != url or url.startswith("https://youtu")
    assert detect(row, svc.blobs) == kind
