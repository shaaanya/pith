import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from infoparser.config import load_config
from infoparser.pipeline import runner
from infoparser.pipeline.extractors import media, web
from infoparser.pipeline.extractors.base import ExtractCtx, NeedsClarificationError
from infoparser.pipeline.extractors.vtt import parse_vtt
from infoparser.providers.ports import ProviderError, TimedText
from infoparser.worker import Failed, NeedsClarification, Processed

FIX = Path(__file__).parent / "fixtures"
FAKE = str(Path(__file__).parent / "stubs" / "fake_ytdlp.py")
HAVE_FFMPEG = shutil.which("ffmpeg") is not None
needs_ffmpeg = pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg not installed")


class Reg:
    def __init__(self, **tasks):
        self.tasks = tasks

    def first(self, task):
        return self.tasks.get(task)


class Transcriber:
    def __init__(self, items=None):
        self.calls, self.items = [], items or [TimedText(0.0, 4.5, "spoken words here"), TimedText(4.5, 9.0, "more talk")]

    def transcribe(self, path, language=None):
        self.calls.append(Path(path))
        assert Path(path).exists()
        return self.items


class Vision:
    def __init__(self):
        self.calls = []

    def describe(self, images, prompt):
        self.calls.append(list(images))
        return "a test pattern"


@pytest.fixture
def env(tmp_path, monkeypatch):
    log = tmp_path / "ytdlp.log"
    monkeypatch.setenv("FAKE_YTDLP_LOG", str(log))
    monkeypatch.delenv("FAKE_YTDLP_MODE", raising=False)
    cfg = load_config(env={"INFOPARSER_HOME": str(tmp_path / "home"), "INFOPARSER_YT_DLP": FAKE})
    dirs = []
    real = tempfile.mkdtemp
    monkeypatch.setattr(tempfile, "mkdtemp", lambda *a, **k: dirs.append(real(*a, **k)) or dirs[-1])

    def calls():
        return [json.loads(l) for l in log.read_text().splitlines()] if log.exists() else []
    return SimpleNamespace(cfg=cfg, dirs=dirs, calls=calls)


def url_ctx(env, url="https://www.youtube.com/watch?v=vid123", **reg):
    row = {"canonical_url": url, "blob_sha256": None, "original_filename": None, "payload_text": url}
    return ExtractCtx(row, None, Reg(**reg), env.cfg)


def test_parse_vtt_dedupes_rolling_captions_and_timestamps():
    got = parse_vtt((FIX / "sample.en.vtt").read_text())
    assert [(t.start, t.end, t.text) for t in got] == [
        (0.0, 2.0, "hello and welcome to the channel"),
        (2.01, 4.0, "today we talk about search & ranking"),
        (4.01, 6.0, "and embedding models"),
    ]
    assert parse_vtt("") == [] and parse_vtt("WEBVTT\n\n") == []
    assert parse_vtt("WEBVTT\n\n01:02.500 --> 01:04,000\nshort form\n")[0].start == 62.5


def test_media_uses_captions_without_downloading(env):
    ex = media.extract(url_ctx(env))
    assert ex.content_type == "video" and ex.title == "Search and ranking 101" and ex.author == "Some Channel"
    assert [t.text for t in ex.timed][0] == "hello and welcome to the channel" and "ranking" in ex.text
    assert all("-x" not in c and "-f" not in c for c in env.calls())
    assert all(c[-2] == "--" for c in env.calls())  # URL only after --
    assert env.dirs and not any(Path(d).exists() for d in env.dirs)


def test_media_falls_back_to_transcriber(env, monkeypatch):
    monkeypatch.setenv("FAKE_YTDLP_MODE", "nocaptions")
    tr = Transcriber()
    ex = media.extract(url_ctx(env, transcribe=tr))
    assert [t.text for t in ex.timed] == ["spoken words here", "more talk"]
    assert any("-x" in c for c in env.calls())
    assert tr.calls and not any(Path(d).exists() for d in env.dirs)
    from infoparser.pipeline.chunk import chunk_timed
    assert chunk_timed(ex.timed)[0][1] == "t=0-9"


def test_media_no_captions_no_transcriber_needs_clarification(env, monkeypatch):
    monkeypatch.setenv("FAKE_YTDLP_MODE", "nocaptions")
    with pytest.raises(NeedsClarificationError, match="no captions and no transcription backend"):
        media.extract(url_ctx(env))
    assert not any("-x" in c for c in env.calls())  # nothing downloaded just to fail
    assert not any(Path(d).exists() for d in env.dirs)


@pytest.mark.parametrize("exc", [RuntimeError("boom"), KeyboardInterrupt()])
def test_media_tempdir_removed_on_error(env, monkeypatch, exc):
    monkeypatch.setenv("FAKE_YTDLP_MODE", "nocaptions")

    class Bad:
        def transcribe(self, path, language=None):
            raise exc
    with pytest.raises(type(exc)):
        media.extract(url_ctx(env, transcribe=Bad()))
    assert env.dirs and not any(Path(d).exists() for d in env.dirs)


@pytest.mark.parametrize("url", ["https://www.instagram.com/reel/abc/", "https://www.tiktok.com/@u/video/1"])
def test_login_failure_needs_clarification_with_caption(env, monkeypatch, url):
    monkeypatch.setenv("FAKE_YTDLP_MODE", "login")
    monkeypatch.setattr(web, "fetch", lambda u, **k: web.FetchResult(
        200, "text/html", b'<html><head><meta property="og:description" content="cool reel caption #fun">'
                          b'</head></html>', u))
    with pytest.raises(NeedsClarificationError) as e:
        media.extract(url_ctx(env, url=url))
    assert "cool reel caption" in e.value.reason and "login" in e.value.reason.lower()
    assert not any(Path(d).exists() for d in env.dirs)


def test_login_failure_survives_unreachable_page(env, monkeypatch):
    monkeypatch.setenv("FAKE_YTDLP_MODE", "login")
    monkeypatch.setattr(web, "fetch", lambda *a, **k: (_ for _ in ()).throw(OSError("offline")))
    with pytest.raises(NeedsClarificationError):
        media.extract(url_ctx(env, url="https://www.instagram.com/reel/abc/"))


def test_other_failure_is_plain_error_and_timeout(env, monkeypatch):
    monkeypatch.setenv("FAKE_YTDLP_MODE", "fail")
    with pytest.raises(RuntimeError, match="404"):
        media.extract(url_ctx(env))
    monkeypatch.setenv("FAKE_YTDLP_MODE", "hang")
    monkeypatch.setattr(media, "INFO_TIMEOUT", 0.5)
    with pytest.raises(RuntimeError, match="timed out"):
        media.extract(url_ctx(env))
    assert not any(Path(d).exists() for d in env.dirs)


def test_missing_binary_needs_clarification(env):
    env.cfg.yt_dlp_binary = "/nonexistent/yt-dlp"
    with pytest.raises(NeedsClarificationError, match="yt-dlp"):
        media.extract(url_ctx(env))


def test_runner_end_to_end_url_captions(env, svc, monkeypatch):
    svc.cfg.yt_dlp_binary = FAKE
    iid = svc.inbox.submit(adapter="t", text="https://www.youtube.com/watch?v=vid123").id
    assert isinstance(runner.process(svc, iid), Processed)
    assert svc.inbox.get(iid)["content_type"] == "video"
    assert [r["locator"] for r in svc.conn.execute("SELECT locator FROM segments")] == ["t=0-6"]


# ---- local files (real ffmpeg) ----
def make_media(tmp_path, kind):
    out = tmp_path / ("clip.wav" if kind == "wav" else f"{kind}.mp4")
    args = {"wav": ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", "1"],
            "mp4": ["-f", "lavfi", "-i", "testsrc=size=64x48:rate=5", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
                    "-t", "7", "-pix_fmt", "yuv420p"],
            "silent": ["-f", "lavfi", "-i", "testsrc=size=64x48:rate=5", "-t", "7", "-pix_fmt", "yuv420p"]}[kind]
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args, str(out)], check=True)
    return out


def file_ctx(env, tmp_path, path, **reg):
    from infoparser.store.blobs import BlobStore
    blobs = BlobStore(tmp_path / "blobs")
    sha = blobs.put_file(path)
    row = {"canonical_url": None, "blob_sha256": sha, "original_filename": path.name, "payload_text": None}
    return ExtractCtx(row, blobs, Reg(**reg), env.cfg)


@needs_ffmpeg
def test_local_wav_is_converted_to_16k_mono_for_transcriber(env, tmp_path):
    seen = {}

    class Probe(Transcriber):
        def transcribe(self, path, language=None):
            seen["info"] = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "stream=sample_rate,channels", "-of", "csv=p=0", str(path)],
                capture_output=True, text=True).stdout.strip() if shutil.which("ffprobe") else "16000,1"
            return super().transcribe(path, language)
    ex = media.extract(file_ctx(env, tmp_path, make_media(tmp_path, "wav"), transcribe=Probe()))
    assert seen["info"] == "16000,1" and ex.content_type == "audio" and ex.timed
    assert not any(Path(d).exists() for d in env.dirs)


@needs_ffmpeg
def test_local_file_without_transcriber_needs_clarification(env, tmp_path):
    with pytest.raises(NeedsClarificationError, match="no transcription backend"):
        media.extract(file_ctx(env, tmp_path, make_media(tmp_path, "wav")))


@needs_ffmpeg
def test_frames_only_with_vision_and_short_transcript(env, tmp_path):
    mp4 = make_media(tmp_path, "mp4")
    v = Vision()
    ex = media.extract(file_ctx(env, tmp_path, mp4, transcribe=Transcriber(), describe=v))
    assert len(v.calls) == 1 and 2 <= len(v.calls[0]) <= 3  # 7s at fps=1/3 -> frames at 0,3,6
    assert any("a test pattern" in t.text for t in ex.timed) and ex.content_type == "video"
    # long transcript: no frames
    v2 = Vision()
    long = Transcriber([TimedText(0, 5, "x" * 250)])
    media.extract(file_ctx(env, tmp_path, mp4, transcribe=long, describe=v2))
    assert v2.calls == []
    # no vision backend: no frames, still fine
    media.extract(file_ctx(env, tmp_path, mp4, transcribe=Transcriber()))
    assert not any(Path(d).exists() for d in env.dirs)


@needs_ffmpeg
def test_silent_video_uses_frames_without_transcriber_or_needs_clarification(env, tmp_path):
    mp4 = make_media(tmp_path, "silent")
    v = Vision()
    ex = media.extract(file_ctx(env, tmp_path, mp4, describe=v))
    assert v.calls and "a test pattern" in ex.text
    with pytest.raises(NeedsClarificationError, match="no audio track"):
        media.extract(file_ctx(env, tmp_path, mp4))


@needs_ffmpeg
def test_url_video_download_for_frames(env, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_YTDLP_MODE", "nocaptions")
    monkeypatch.setenv("FAKE_YTDLP_VIDEO", str(make_media(tmp_path, "mp4")))
    v = Vision()
    ex = media.extract(url_ctx(env, transcribe=Transcriber(), describe=v))
    assert v.calls and any("a test pattern" in t.text for t in ex.timed)
    assert not any(Path(d).exists() for d in env.dirs)


def test_ffmpeg_missing_needs_clarification(env, tmp_path):
    p = tmp_path / "a.wav"
    p.write_bytes(b"RIFFxxxxWAVE")
    env.cfg.ffmpeg_binary = "/nonexistent/ffmpeg"
    with pytest.raises(NeedsClarificationError, match="ffmpeg"):
        media.extract(file_ctx(env, tmp_path, p, transcribe=Transcriber()))


# ---- fix round 1 ----
class FlakyVision(Vision):
    def describe(self, images, prompt):
        raise ProviderError("vision down")


@needs_ffmpeg
def test_flaky_vision_keeps_captions_and_records_error(env, svc, monkeypatch):
    ex = media.extract(url_ctx(env, describe=FlakyVision()))  # short captions + vision configured
    assert "ranking" in ex.text and ex.timed
    # no video downloaded by fake in captions mode -> still contained
    assert "frames_error" in ex.metadata
    assert not any(Path(d).exists() for d in env.dirs)


@needs_ffmpeg
def test_local_vision_failure_keeps_transcript(env, tmp_path):
    ex = media.extract(file_ctx(env, tmp_path, make_media(tmp_path, "mp4"), transcribe=Transcriber(),
                                describe=FlakyVision()))
    assert ex.text.startswith("spoken words") and "ProviderError" in ex.metadata["frames_error"]
    assert not any(Path(d).exists() for d in env.dirs)


@needs_ffmpeg
def test_ffmpeg_frame_failure_contained(env, tmp_path, monkeypatch):
    monkeypatch.setattr(media, "_frames", lambda *a: (_ for _ in ()).throw(RuntimeError("ffmpeg failed: x")))
    ex = media.extract(file_ctx(env, tmp_path, make_media(tmp_path, "mp4"), transcribe=Transcriber(),
                                describe=Vision()))
    assert ex.timed and "ffmpeg failed" in ex.metadata["frames_error"]


@needs_ffmpeg
def test_visual_item_has_real_range_locator(env, tmp_path):
    from infoparser.pipeline.chunk import chunk_timed
    ex = media.extract(file_ctx(env, tmp_path, make_media(tmp_path, "silent"), describe=Vision()))
    v = ex.timed[0]
    assert v.start == 0 and v.end == 6.0 and v.text.startswith("[visual]")
    loc = chunk_timed(ex.timed)[0][1]
    assert loc != "t=0-0" and loc.startswith("t=0-")
    ex2 = media.extract(file_ctx(env, tmp_path, make_media(tmp_path, "mp4"), transcribe=Transcriber(), describe=Vision()))
    assert {t.text for t in ex2.timed} == {"spoken words here", "more talk", "[visual] a test pattern"}
    assert chunk_timed(ex2.timed)[0][1] == "t=0-9"


def test_subtitle_fetch_failure_falls_back_to_transcription(env, monkeypatch):
    monkeypatch.setenv("FAKE_YTDLP_MODE", "subfail")
    ex = media.extract(url_ctx(env, transcribe=Transcriber()))
    assert ex.timed[0].text == "spoken words here" and ex.title == "Search and ranking 101"
    monkeypatch.setattr(media, "_caption_from_page", lambda u: None)
    with pytest.raises(NeedsClarificationError, match="no transcription"):
        media.extract(url_ctx(env))


def test_social_host_match_is_exact(env, monkeypatch):
    monkeypatch.setenv("FAKE_YTDLP_MODE", "fail")
    with pytest.raises(RuntimeError):  # 404 on a lookalike host is a plain error, not a login clarification
        media.extract(url_ctx(env, url="https://notinstagram.com/reel/abc"))


def test_empty_dump_json_clean_error(env, monkeypatch):
    monkeypatch.setenv("FAKE_YTDLP_MODE", "emptyjson")
    with pytest.raises(RuntimeError, match="no metadata"):
        media.extract(url_ctx(env))


def test_max_filesize_flag_and_local_size_cap(env, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_YTDLP_MODE", "nocaptions")
    media.extract(url_ctx(env, transcribe=Transcriber()))
    dl = [c for c in env.calls() if "-x" in c][0]
    assert dl[dl.index("--max-filesize") + 1] == str(env.cfg.max_fetch_bytes)
    p = tmp_path / "a.wav"
    p.write_bytes(b"RIFFxxxxWAVE" * 10)
    env.cfg.max_fetch_bytes = 5
    with pytest.raises(NeedsClarificationError, match="max_fetch_bytes"):
        media.extract(file_ctx(env, tmp_path, p, transcribe=Transcriber()))


def test_dash_url_is_after_double_dash(env):
    media.extract(url_ctx(env, url="--exec=touch /tmp/pwned"))
    assert env.calls() and all(c[-2:] == ["--", "--exec=touch /tmp/pwned"] for c in env.calls())


def test_vtt_hours_and_empty_cue():
    got = parse_vtt("WEBVTT\n\n01:02:03.500 --> 01:02:05.000\nhour cue\n\n"
                    "01:02:05.000 --> 01:02:06.000\n\n01:02:06.000 --> 01:02:07.000\n<c></c>\n")
    assert [(t.start, t.end, t.text) for t in got] == [(3723.5, 3725.0, "hour cue")]


def test_login_clarification_is_pasteable_because_it_invites_pasting():
    e = media._login_clarification("https://www.instagram.com/reel/x/", "login", {"title": "t"})
    assert "paste" in e.reason and e.pasteable is True
