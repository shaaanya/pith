"""REAL ffmpeg/ffprobe on media generated at test time (a blue clip with a 440 Hz tone).

Genuine external evidence for the media extractor's local-file path (stream probe, 16 kHz mono wav
extraction, frame extraction). The transcriber and vision backends are scripted: no whisper or
vision model is installed, so the model-side of this path is NOT verified here.
"""
import pytest
from realtools import Probe, Reg, Vision, make_av, needs

from infoparser.config import load_config
from infoparser.pipeline import runner
from infoparser.pipeline.extractors import media
from infoparser.pipeline.extractors.base import ExtractCtx, NeedsClarificationError
from infoparser.worker import NeedsClarification

pytestmark = needs("ffmpeg", "ffprobe")


def _ctx(tmp_path, svc_blobs, path, **reg):
    cfg = load_config(env={"INFOPARSER_HOME": str(tmp_path / "home")})
    row = {"canonical_url": None, "blob_sha256": svc_blobs.put_file(path),
           "original_filename": path.name, "payload_text": None}
    return ExtractCtx(row, svc_blobs, Reg(**reg), cfg)


def test_stream_probe_and_wav16_and_frames_with_real_ffmpeg(svc, tmp_path):
    """7 s blue clip + tone: wav is 16 kHz mono ~7 s and audible; frames are JPEGs and blue."""
    clip = make_av(tmp_path / "clip.mp4", seconds=7)
    t, v = Probe(), Vision()
    ex = media.extract(_ctx(tmp_path, svc.blobs, clip, transcribe=t, describe=v))
    assert t.seen["probe"]["sample_rate"] == "16000" and t.seen["probe"]["channels"] == "1"
    assert t.seen["probe"]["codec_name"] == "pcm_s16le"
    assert 6.5 < float(t.seen["probe"]["duration"]) < 7.5
    assert "mean_volume: -" in t.seen["volume"]  # a real tone: not digital silence (-inf)
    assert "mean_volume: -inf" not in t.seen["volume"]
    assert 2 <= len(v.frames) <= 3  # fps=1/3 over 7 s
    for magic, (r, _g, b) in v.frames:
        assert magic == b"\xff\xd8" and b > 150 and r < 80  # JPEG, blue
    assert ex.content_type == "video" and "scripted description" in ex.text


def test_audio_only_file_has_no_frames(svc, tmp_path):
    """Audio-only input: content type audio, vision never called, transcriber got the wav."""
    clip = make_av(tmp_path / "tone.m4a", seconds=2, video=False)
    t, v = Probe(), Vision()
    ex = media.extract(_ctx(tmp_path, svc.blobs, clip, transcribe=t, describe=v))
    assert ex.content_type == "audio" and not v.frames and t.seen["probe"]["sample_rate"] == "16000"


def test_missing_transcriber_and_silent_video_degrade(svc, tmp_path):
    """Real stream probe: audio sans transcriber, and video sans audio, ask for clarification."""
    with_audio = make_av(tmp_path / "a.mp4", seconds=2)
    with pytest.raises(NeedsClarificationError, match="no transcription backend"):
        media.extract(_ctx(tmp_path, svc.blobs, with_audio))
    silent = make_av(tmp_path / "s.mp4", seconds=2, audio=False)
    with pytest.raises(NeedsClarificationError, match="no audio track"):
        media.extract(_ctx(tmp_path, svc.blobs, silent))


def test_runner_path_without_whisper_is_needs_clarification(svc, tmp_path):
    """Whole pipeline, default config (no transcribe backend): item -> needs_clarification."""
    clip = make_av(tmp_path / "talk.mp4", seconds=2)
    iid = svc.inbox.submit(adapter="t", file=clip.read_bytes(), filename="talk.mp4").id
    out = runner.process(svc, iid)
    assert isinstance(out, NeedsClarification) and "no transcription backend" in out.reason


def test_garbage_file_named_mp4_is_rejected_cleanly(svc, tmp_path):
    """ffmpeg cannot read it: needs_clarification, not a crash."""
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"not media at all" * 50)
    with pytest.raises(NeedsClarificationError):
        media.extract(_ctx(tmp_path, svc.blobs, bad, transcribe=Probe()))
