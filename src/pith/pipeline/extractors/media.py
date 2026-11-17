"""Video/audio extraction, captions first.

URL: yt-dlp metadata + existing (manual or auto) subtitles -> timed text, nothing downloaded. Only
when there are no captions AND a `transcribe` backend is configured is audio downloaded and
transcribed. Local files go straight to the transcriber after ffmpeg -> 16 kHz mono wav. Frames
(ffmpeg -vf fps=1/3) go to a `describe` (vision) backend only when one is configured and the
transcript is < 200 chars.

The URL is passed to yt-dlp and cited exactly as submitted (the canonical form is only the dedupe
key); when yt-dlp reports a `webpage_url` that is cited instead. Checked against real yt-dlp
(generic extractor, loopback): it echoes a direct URL back unchanged and reports the target of a
redirect; other extractors are UNVERIFIED.

Honest limits: captions are English-only (en/en.* tracks); other-language captions are ignored and
the item falls back to transcription (or asks for clarification). Instagram/TikTok extraction
usually needs cookies/login and is rate-limited; on such a failure we raise
NeedsClarificationError carrying the page caption (og:description) if reachable. That path is
tested only against a fake yt-dlp -- real Instagram/TikTok behaviour is UNVERIFIED here. Whisper is
not installed here, so real transcription is unverified too (tests use stub transcribers).
All subprocess calls use argument lists (no shell), timeouts, and the URL after `--`.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

from pith import netguard
from pith.domain.display import submitted_url

from pith.pipeline.extractors import web
from pith.pipeline.extractors.base import (
    Extracted,
    ExtractCtx,
    NeedsClarificationError,
    register,
)
from pith.pipeline.extractors.vtt import parse_vtt
from pith.providers.ports import TimedText

INFO_TIMEOUT = 60  # seconds; module-level so tests can shorten
DOWNLOAD_TIMEOUT = 900
FFMPEG_TIMEOUT = 600
FRAME_SECONDS, MAX_FRAMES, SHORT_TRANSCRIPT = 3, 8, 200
NO_TRANSCRIBER = "no captions and no transcription backend"
_SOCIAL = ("instagram.com", "tiktok.com")
_clock, _sleep = time.monotonic, time.sleep  # module-level so tests can replace them
_last: dict[str, float] = {}  # cookie host -> when its last logged-in fetch was allowed to start
_last_lock = threading.Lock()
_LOGIN = re.compile(
    r"login|log in|sign in|cookies|rate.?limit|private|not available|empty media|requires? auth",
    re.I,
)
_OG = re.compile(
    r'<meta[^>]+(?:property|name)=["\'](?:og:)?description["\'][^>]+content=["\']([^"\']*)', re.I
)


def _throttle(host: str, gap: float) -> None:
    """Space logged-in fetches to one host `gap` seconds apart: a human-like pace is what keeps
    the account behind the browser session from being flagged."""
    with _last_lock:
        now = _clock()
        start = max(now, _last.get(host, now - gap) + gap)
        _last[host] = start
    if start > now:
        _sleep(start - now)


def _run(cmd: list[str], timeout: float, what: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, errors="replace", timeout=timeout, shell=False,
            check=False
        )
    except FileNotFoundError:
        raise NeedsClarificationError(
            f"{what} not found ({cmd[0]}); install it or set its path in config"
        ) from None
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"{what} timed out after {timeout}s") from None


class MediaToolError(RuntimeError):
    """yt-dlp exited non-zero; the message is its (trimmed) stderr."""


class YtDlp:
    """Thin yt-dlp wrapper: argument lists only, URL after `--`."""

    def __init__(self, binary: str = "yt-dlp", max_bytes: int | None = None,
                 cookies: str | None = None):
        self.binary, self.max_bytes = binary, max_bytes
        # cookies: a validated --cookies-from-browser value (config rejects anything flag-like)
        self.auth = ["--cookies-from-browser", cookies, "--sleep-requests", "1"] if cookies else []
        self.size = ["--max-filesize", str(max_bytes)] if max_bytes else []

    def _ok(self, cmd, timeout):
        r = _run(cmd, timeout, "yt-dlp")
        if r.returncode != 0:
            raise MediaToolError((r.stderr or r.stdout or "yt-dlp failed").strip()[-500:])
        return r

    def _found(self, tmpdir, pattern, r, optional=False) -> Path:
        files = sorted(Path(tmpdir).glob(pattern))
        if files:
            return files[0]
        if "larger than max-filesize" in r.stdout:  # real yt-dlp skips the file and exits 0
            msg = f"media larger than max_fetch_bytes ({self.max_bytes})"
            raise MediaToolError(msg) if optional else NeedsClarificationError(msg)
        raise MediaToolError("yt-dlp produced no file")

    def info_and_subs(self, url: str, tmpdir: Path) -> tuple[dict, Path | None]:
        """Metadata plus the first English caption file, if any (nothing else downloaded)."""
        base = [self.binary, "--no-playlist", "--no-warnings", *self.auth]
        out = self._ok([*base, "--dump-json", "--", url], INFO_TIMEOUT).stdout.strip()
        if not out:
            raise MediaToolError("yt-dlp returned no metadata")
        info = json.loads(out.splitlines()[0])
        try:
            self._ok(
                [
                    *base,
                    "--skip-download",
                    "--write-subs",
                    "--write-auto-subs",
                    "--sub-langs",
                    "en.*,en",
                    "--sub-format",
                    "vtt",
                    "-o",
                    str(Path(tmpdir) / "sub.%(ext)s"),
                    "--",
                    url,
                ],
                INFO_TIMEOUT,
            )
        except (
            MediaToolError
        ) as e:  # e.g. 429 on the subtitle fetch: caller falls back to transcription
            info["_subs_error"] = str(e)
        vtts = sorted(
            Path(tmpdir).glob("sub*.vtt"), key=lambda p: (".en." not in p.name, len(p.name), p.name)
        )
        return info, (vtts[0] if vtts else None)

    def download_audio(self, url: str, tmpdir: Path) -> Path:
        """Download the audio track for transcription."""
        r = self._ok(
            [
                self.binary,
                "--no-playlist",
                "--no-warnings",
                *self.auth,
                *self.size,
                "-x",
                "--audio-format",
                "wav",
                "-o",
                str(Path(tmpdir) / "audio.%(ext)s"),
                "--",
                url,
            ],
            DOWNLOAD_TIMEOUT,
        )
        return self._found(tmpdir, "audio.*", r)

    def download_video(self, url: str, tmpdir: Path) -> Path:
        """Download the video for frame description."""
        r = self._ok(
            [
                self.binary,
                "--no-playlist",
                "--no-warnings",
                *self.auth,
                *self.size,
                "-f",
                "worst[ext=mp4]/worst",
                "-o",
                str(Path(tmpdir) / "video.%(ext)s"),
                "--",
                url,
            ],
            DOWNLOAD_TIMEOUT,
        )
        return self._found(tmpdir, "video.*", r, optional=True)


def _ffmpeg(cfg, args: list[str]) -> None:
    r = _run([cfg.ffmpeg_binary, "-y", "-loglevel", "error", *args], FFMPEG_TIMEOUT, "ffmpeg")
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {r.stderr.strip()[-300:]}")


def _caption_from_page(url: str, untrusted: bool = False) -> str | None:
    try:
        res = web.fetch(url, max_bytes=2_000_000, timeout=10, untrusted=untrusted)
        m = _OG.search(res.body.decode("utf-8", "replace"))
        return re.sub(r"\s+", " ", m.group(1)).strip() or None if m else None
    except Exception:  # pylint: disable=broad-exception-caught  # best effort only
        return None


def _login_clarification(
    url: str, err: str, info: dict | None, untrusted: bool = False, cookies: str | None = None
) -> NeedsClarificationError:
    caption = (
        (info or {}).get("description")
        or (info or {}).get("title")
        or (_caption_from_page(url, True) if untrusted else _caption_from_page(url))
    )
    where = url.split("/")[2] if "//" in url else url
    msg = f"login or rate limit from {where}; paste the transcript or text"
    if cookies:
        msg += (f". Fetched with your browser session ({cookies}), which may have expired: log in "
                f"again in that browser profile. yt-dlp said: {err.replace(url, '<url>')[:200]}")
    if caption:
        msg += f". Caption found: {caption[:300]}"
    return NeedsClarificationError(msg, pasteable=True)


def _frames(cfg, video: Path, tmpdir: Path) -> list[Path]:
    out = Path(tmpdir) / "frames"
    out.mkdir(exist_ok=True)
    _ffmpeg(
        cfg,
        [
            "-i",
            str(video),
            "-vf",
            f"fps=1/{FRAME_SECONDS}",
            "-frames:v",
            str(MAX_FRAMES),
            str(out / "f_%03d.jpg"),
        ],
    )
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
        desc = (
            vision.describe(
                frames, "Describe what is shown in these video frames, including any visible text."
            )
            or ""
        ).strip()
    except Exception as e:  # pylint: disable=broad-exception-caught  # frames are best effort
        return timed, f"{type(e).__name__}: {getattr(e, 'reason', e)}"
    if not desc:
        return timed, None
    end = len(frames) * FRAME_SECONDS
    end = min(end, duration) if duration else end
    return sorted(
        [*timed, TimedText(0.0, float(end), f"[visual] {desc}")], key=lambda t: t.start
    ), None


def _wav16(cfg, src: Path, tmp: Path) -> Path:
    wav = Path(tmp) / "audio16k.wav"
    _ffmpeg(cfg, ["-i", str(src), "-vn", "-ac", "1", "-ar", "16000", str(wav)])
    return wav


def _transcribe(ctx, src: Path, tmp: Path) -> list[TimedText]:
    return list(ctx.registry.first("transcribe").transcribe(_wav16(ctx.cfg, src, tmp), None))


@register("video", "audio")
def extract(ctx: ExtractCtx) -> Extracted:
    """URL via yt-dlp, or a local audio/video file via ffmpeg and the transcriber."""
    row, cfg = ctx.row, ctx.cfg
    url = submitted_url(row)
    tmp = Path(tempfile.mkdtemp(prefix="pith-media-"))
    try:
        if url:
            return _from_url(ctx, url, tmp)
        sha = row["blob_sha256"]
        if not sha:
            raise NeedsClarificationError("media item has neither URL nor file")
        path = ctx.blobs.path(sha)
        if path.stat().st_size > cfg.max_fetch_bytes:
            raise NeedsClarificationError(
                f"media file larger than max_fetch_bytes ({cfg.max_fetch_bytes})"
            )
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
        return _result(
            row["original_filename"] or "Media file",
            None,
            None,
            "video" if has_video else "audio",
            timed,
            sha,
            ferr,
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _streams(cfg, path: Path) -> tuple[bool, bool, float | None]:
    # ffmpeg -i prints stream info to stderr and exits 1 without an output file (expected).
    r = _run([cfg.ffmpeg_binary, "-hide_banner", "-i", str(path)], 60, "ffmpeg")
    video = bool(re.search(r"Stream #.*Video:", r.stderr)) and "attached pic" not in r.stderr
    audio = bool(re.search(r"Stream #.*Audio:", r.stderr))
    if not (video or audio):
        raise NeedsClarificationError("file has no audio or video stream ffmpeg can read")
    m = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", r.stderr)
    return video, audio, (int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]) if m else None)


# pylint: disable-next=too-many-arguments,too-many-positional-arguments  # Extracted fields
def _result(title, author, url, ctype, timed, sha=None, frames_error=None,
            description=None) -> Extracted:
    timed = [t for t in timed if t.text.strip()]
    if not timed:
        raise NeedsClarificationError("no speech or text could be extracted from the media")
    meta = {"frames_error": frames_error} if frames_error else {}
    if description:
        meta["description"] = description
    return Extracted(
        title,
        author,
        url,
        ctype,
        " ".join(t.text for t in timed),
        timed=timed,
        original_sha=sha,
        metadata=meta,
    )


def _from_url(ctx: ExtractCtx, url: str, tmp: Path) -> Extracted:
    if netguard.untrusted(ctx.row):
        # yt-dlp follows its own redirects outside the guard (a documented limitation): only hand
        # it a URL whose host resolves to public addresses.
        netguard.check_url(url, allow_private=False)
    host = (urlparse(url).hostname or "").removeprefix("www.")
    cookie_host = next((d for d in ctx.cfg.cookie_domains if host == d or host.endswith("." + d)),
                       None)
    cookies = ctx.cfg.cookies_from_browser if cookie_host else None
    yt = YtDlp(ctx.cfg.yt_dlp_binary, ctx.cfg.max_fetch_bytes, cookies)
    if cookies:
        _throttle(cookie_host, ctx.cfg.cookie_gap_seconds)
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
                timed, ferr = _add_frames(
                    ctx, yt.download_video(url, tmp), tmp, timed, info.get("duration")
                )
            except (
                MediaToolError,
                RuntimeError,
            ) as e:  # download failure/timeout: frames are optional
                ferr = f"{type(e).__name__}: {e}"
    except MediaToolError as e:
        if social or _LOGIN.search(str(e).replace(url, "")):  # yt-dlp may echo the URL
            raise _login_clarification(url, str(e), info, netguard.untrusted(ctx.row),
                                       cookies) from e
        raise RuntimeError(f"yt-dlp: {e}") from e
    ctype = "audio" if info.get("vcodec") == "none" else "video"
    cited = info.get("webpage_url") or url  # what yt-dlp says served it, else as submitted
    return _result(info.get("title"), info.get("uploader"), cited, ctype, timed, frames_error=ferr,
                   description=info.get("description"))
