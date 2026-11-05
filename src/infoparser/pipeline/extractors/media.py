"""Video/audio extraction, captions first.

URL: yt-dlp metadata + existing (manual or auto) subtitles -> timed text, nothing downloaded. Only when
there are no captions AND a `transcribe` backend is configured is audio downloaded and transcribed.
Local files go straight to the transcriber after ffmpeg -> 16 kHz mono wav. Frames (ffmpeg -vf fps=1/3)
go to a `describe` (vision) backend only when one is configured and the transcript is < 200 chars.

Honest limits: captions are English-only (en/en.* tracks); other-language captions are ignored and the item
falls back to transcription (or asks for clarification). Instagram/TikTok extraction usually needs cookies/login and is rate-limited; on such a
failure we raise NeedsClarificationError carrying the page caption (og:description) if reachable. That
path is tested only against a fake yt-dlp -- real Instagram/TikTok behaviour is UNVERIFIED here. Whisper is
not installed here, so real transcription is unverified too (tests use stub transcribers).
All subprocess calls use argument lists (no shell), timeouts, and the URL after `--`.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from urllib.parse import urlparse
from pathlib import Path

from infoparser.pipeline.extractors import web
from infoparser.pipeline.extractors.base import Extracted, ExtractCtx, NeedsClarificationError, register
from infoparser.pipeline.extractors.vtt import parse_vtt
from infoparser.providers.ports import TimedText

INFO_TIMEOUT = 60  # seconds; module-level so tests can shorten
DOWNLOAD_TIMEOUT = 900
FFMPEG_TIMEOUT = 600
FRAME_SECONDS, MAX_FRAMES, SHORT_TRANSCRIPT = 3, 8, 200
NO_TRANSCRIBER = "no captions and no transcription backend"
_SOCIAL = ("instagram.com", "tiktok.com")
_LOGIN = re.compile(r"login|log in|sign in|cookies|rate.?limit|private|not available|empty media|requires? auth", re.I)
_OG = re.compile(r'<meta[^>]+(?:property|name)=["\'](?:og:)?description["\'][^>]+content=["\']([^"\']*)', re.I)


def _run(cmd: list[str], timeout: float, what: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=timeout, shell=False)
    except FileNotFoundError:
        raise NeedsClarificationError(f"{what} not found ({cmd[0]}); install it or set its path in config") from None
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"{what} timed out after {timeout}s") from None


class MediaToolError(RuntimeError):
    pass


class YtDlp:
    def __init__(self, binary: str = "yt-dlp", max_bytes: int | None = None):
        self.binary = binary
        self.size = ["--max-filesize", str(max_bytes)] if max_bytes else []

    def _ok(self, cmd, timeout):
        r = _run(cmd, timeout, "yt-dlp")
        if r.returncode != 0:
            raise MediaToolError((r.stderr or r.stdout or "yt-dlp failed").strip()[-500:])
        return r

    def info_and_subs(self, url: str, tmpdir: Path) -> tuple[dict, Path | None]:
        import json
        base = [self.binary, "--no-playlist", "--no-warnings"]
        out = self._ok([*base, "--dump-json", "--", url], INFO_TIMEOUT).stdout.strip()
        if not out:
            raise MediaToolError("yt-dlp returned no metadata")
        info = json.loads(out.splitlines()[0])
        try:
            self._ok([*base, "--skip-download", "--write-subs", "--write-auto-subs", "--sub-langs", "en.*,en",
                  "--sub-format", "vtt", "-o", str(Path(tmpdir) / "sub.%(ext)s"), "--", url], INFO_TIMEOUT)
        except MediaToolError as e:  # e.g. 429 on the subtitle fetch: caller falls back to transcription
            info["_subs_error"] = str(e)
        vtts = sorted(Path(tmpdir).glob("sub*.vtt"), key=lambda p: (".en." not in p.name, len(p.name), p.name))
        return info, (vtts[0] if vtts else None)

    def download_audio(self, url: str, tmpdir: Path) -> Path:
        self._ok([self.binary, "--no-playlist", "--no-warnings", *self.size, "-x", "--audio-format", "wav",
                  "-o", str(Path(tmpdir) / "audio.%(ext)s"), "--", url], DOWNLOAD_TIMEOUT)
        return self._found(tmpdir, "audio.*")

    def download_video(self, url: str, tmpdir: Path) -> Path:
        self._ok([self.binary, "--no-playlist", "--no-warnings", *self.size, "-f", "worst[ext=mp4]/worst",
                  "-o", str(Path(tmpdir) / "video.%(ext)s"), "--", url], DOWNLOAD_TIMEOUT)
        return self._found(tmpdir, "video.*")

    @staticmethod
    def _found(tmpdir, pattern) -> Path:
        files = sorted(Path(tmpdir).glob(pattern))
        if not files:
            raise MediaToolError("yt-dlp produced no file")
        return files[0]


def _ffmpeg(cfg, args: list[str]) -> None:
    r = _run([cfg.ffmpeg_binary, "-y", "-loglevel", "error", *args], FFMPEG_TIMEOUT, "ffmpeg")
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {r.stderr.strip()[-300:]}")


def _caption_from_page(url: str) -> str | None:
    try:
        res = web.fetch(url, max_bytes=2_000_000, timeout=10)
        m = _OG.search(res.body.decode("utf-8", "replace"))
        return re.sub(r"\s+", " ", m.group(1)).strip() or None if m else None
    except Exception:  # noqa: BLE001 - best effort only, never turns a clarification into a crash
        return None


def _login_clarification(url: str, err: str, info: dict | None) -> NeedsClarificationError:
    caption = (info or {}).get("description") or (info or {}).get("title") or _caption_from_page(url)
    msg = f"login or rate limit from {url.split('/')[2] if '//' in url else url}; paste the transcript or text"
    if caption:
        msg += f". Caption found: {caption[:300]}"
    return NeedsClarificationError(msg, pasteable=True)


def _frames(cfg, video: Path, tmpdir: Path) -> list[Path]:
    out = Path(tmpdir) / "frames"
    out.mkdir(exist_ok=True)
    _ffmpeg(cfg, ["-i", str(video), "-vf", f"fps=1/{FRAME_SECONDS}", "-frames:v", str(MAX_FRAMES),
                  str(out / "f_%03d.jpg")])
    return sorted(out.glob("f_*.jpg"))


def _add_frames(ctx, video: Path, tmp: Path, timed: list[TimedText], duration: float | None = None):
    """Optional step: never loses `timed`. Returns (timed, error_or_None)."""
    vision = ctx.registry.first("describe")
    if vision is None or sum(len(t.text) for t in timed) >= SHORT_TRANSCRIPT:
        return timed, None
    try:
        frames = _frames(ctx.cfg, video, tmp)
        if not frames:
            return timed, None
        desc = (vision.describe(frames, "Describe what is shown in these video frames, including any visible "
                                        "text.") or "").strip()
    except Exception as e:  # noqa: BLE001 - frames are best effort; keep the captions/transcript
        return timed, f"{type(e).__name__}: {getattr(e, 'reason', e)}"
    if not desc:
        return timed, None
    end = len(frames) * FRAME_SECONDS
    end = min(end, duration) if duration else end
    return sorted([*timed, TimedText(0.0, float(end), f"[visual] {desc}")], key=lambda t: t.start), None


def _wav16(cfg, src: Path, tmp: Path) -> Path:
    wav = Path(tmp) / "audio16k.wav"
    _ffmpeg(cfg, ["-i", str(src), "-vn", "-ac", "1", "-ar", "16000", str(wav)])
    return wav


def _transcribe(ctx, src: Path, tmp: Path) -> list[TimedText]:
    return list(ctx.registry.first("transcribe").transcribe(_wav16(ctx.cfg, src, tmp), None))


@register("video", "audio")
def extract(ctx: ExtractCtx) -> Extracted:
    row, cfg = ctx.row, ctx.cfg
    url = row["canonical_url"]
    tmp = Path(tempfile.mkdtemp(prefix="infoparser-media-"))
    try:
        if url:
            return _from_url(ctx, url, tmp)
        sha = row["blob_sha256"]
        if not sha:
            raise NeedsClarificationError("media item has neither URL nor file")
        path = ctx.blobs.path(sha)
        if path.stat().st_size > cfg.max_fetch_bytes:
            raise NeedsClarificationError(f"media file larger than max_fetch_bytes ({cfg.max_fetch_bytes})")
        has_video, has_audio, duration = _streams(cfg, path)
        timed: list[TimedText] = []
        if has_audio:
            if ctx.registry.first("transcribe") is None:
                raise NeedsClarificationError(NO_TRANSCRIBER)
            timed = _transcribe(ctx, path, tmp)
        elif not (has_video and ctx.registry.first("describe")):
            raise NeedsClarificationError("media has no audio track to transcribe")
        ferr = None
        if has_video:
            timed, ferr = _add_frames(ctx, path, tmp, timed, duration)
        return _result(row["original_filename"] or "Media file", None, None, "video" if has_video else "audio",
                       timed, sha, ferr)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _streams(cfg, path: Path) -> tuple[bool, bool, float | None]:
    # ffmpeg -i prints stream info to stderr and exits 1 without an output file; that is expected here.
    r = _run([cfg.ffmpeg_binary, "-hide_banner", "-i", str(path)], 60, "ffmpeg")
    video = bool(re.search(r"Stream #.*Video:", r.stderr)) and "attached pic" not in r.stderr
    audio = bool(re.search(r"Stream #.*Audio:", r.stderr))
    if not (video or audio):
        raise NeedsClarificationError("file has no audio or video stream ffmpeg can read")
    m = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", r.stderr)
    return video, audio, (int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]) if m else None)


def _result(title, author, url, ctype, timed, sha=None, frames_error=None) -> Extracted:
    timed = [t for t in timed if t.text.strip()]
    if not timed:
        raise NeedsClarificationError("no speech or text could be extracted from the media")
    return Extracted(title, author, url, ctype, " ".join(t.text for t in timed), timed=timed, original_sha=sha,
                     metadata={"frames_error": frames_error} if frames_error else {})


def _from_url(ctx: ExtractCtx, url: str, tmp: Path) -> Extracted:
    yt = YtDlp(ctx.cfg.yt_dlp_binary, ctx.cfg.max_fetch_bytes)
    host = (urlparse(url).hostname or "").removeprefix("www.")
    social = any(host == h or host.endswith("." + h) for h in _SOCIAL)
    info: dict = {}
    try:
        info, subs = yt.info_and_subs(url, tmp)
        timed = parse_vtt(subs.read_text("utf-8", "replace")) if subs else []
        if not timed:
            if ctx.registry.first("transcribe") is None:
                raise NeedsClarificationError(NO_TRANSCRIBER)
            audio = yt.download_audio(url, tmp)
            timed = _transcribe(ctx, audio, tmp)
        ferr = None
        if ctx.registry.first("describe") and sum(len(t.text) for t in timed) < SHORT_TRANSCRIPT:
            try:
                timed, ferr = _add_frames(ctx, yt.download_video(url, tmp), tmp, timed, info.get("duration"))
            except (MediaToolError, RuntimeError) as e:  # download failure/timeout: frames are optional
                ferr = f"{type(e).__name__}: {e}"
    except MediaToolError as e:
        if social or _LOGIN.search(str(e)):
            raise _login_clarification(url, str(e), info) from e
        raise RuntimeError(f"yt-dlp: {e}") from e
    ctype = "audio" if info.get("vcodec") == "none" else "video"
    return _result(info.get("title"), info.get("uploader"), url, ctype, timed, frames_error=ferr)
