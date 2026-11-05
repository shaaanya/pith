"""Builders for real-binary tests: tiny PDFs, rendered PNGs, ffmpeg media. Nothing is committed;
everything is generated into tmp paths at test time."""
import shutil
import subprocess
from pathlib import Path

import pytest

from infoparser.providers.ports import TimedText


def have(*binaries) -> bool:
    """True when every binary is on PATH."""
    return all(shutil.which(b) for b in binaries)


def needs(*binaries):
    """Skip marker for tests that need real binaries."""
    return pytest.mark.skipif(not have(*binaries), reason=f"{', '.join(binaries)} not installed")


def run(*argv, **kw) -> subprocess.CompletedProcess:
    """Run a real tool; a failure is a test error with its stderr."""
    r = subprocess.run(list(map(str, argv)), capture_output=True, timeout=120, check=False, **kw)
    assert r.returncode == 0, f"{argv[0]} failed: {r.stderr.decode(errors='replace')[-400:]}"
    return r


def _assemble(objs: list[bytes]) -> bytes:
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def make_pdf(pages: list[list[str]]) -> bytes:
    """A multi-page text PDF (base-14 Helvetica, no embedded font); each page is a list of lines."""
    n = len(pages)
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            f"<< /Type /Pages /Kids [{' '.join(f'{3 + 2 * i} 0 R' for i in range(n))}] "
            f"/Count {n} >>".encode()]
    for i, lines in enumerate(pages):
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                    f"/Contents {4 + 2 * i} 0 R "
                    f"/Resources << /Font << /F1 {3 + 2 * n} 0 R >> >> >>".encode())
        stream = "BT /F1 36 Tf 50 700 Td 40 TL " + " ".join(f"({t}) Tj T*" for t in lines) + " ET"
        objs.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream".encode())
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    return _assemble(objs)


def pdf_page_png(pdf: Path, out: Path, dpi: int = 150) -> Path:
    """Render page 1 of a PDF to PNG with poppler's pdftoppm (-singlefile: exact name)."""
    run("pdftoppm", "-r", dpi, "-png", "-singlefile", "-f", 1, "-l", 1, pdf, out.with_suffix(""))
    return out


def image_pdf(png: Path, out: Path) -> Path:
    """An image-only PDF (scanned page, no text layer): the PNG as a 612x792 JPEG XObject."""
    jpg = out.with_suffix(".jpg")
    ffmpeg("-i", png, "-vf", "scale=612:792", "-update", "1", jpg)
    data = jpg.read_bytes()
    content = b"q 612 0 0 792 0 0 cm /Im0 Do Q"
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
            b"/Resources << /XObject << /Im0 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n%s\nendstream" % (len(content), content),
            b"<< /Type /XObject /Subtype /Image /Width 612 /Height 792 /ColorSpace /DeviceGray"
            b" /BitsPerComponent 8 /Filter /DCTDecode /Length %d >>\nstream\n%s\nendstream"
            % (len(data), data)]
    out.write_bytes(_assemble(objs))
    return out


def ffmpeg(*args) -> None:
    """Run the real ffmpeg quietly."""
    run("ffmpeg", "-y", "-loglevel", "error", *args)


def make_av(out: Path, seconds: int = 4, audio: bool = True, video: bool = True) -> Path:
    """A short mp4 (colour frames) with a 440 Hz tone, or an audio-only/video-only variant."""
    args = []
    if video:
        args += ["-f", "lavfi", "-i", f"color=c=blue:s=160x120:d={seconds}:r=10"]
    if audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    args += ["-c:v", "mpeg4"] if video else []
    args += ["-c:a", "aac"] if audio else []
    args += ["-shortest", out]
    ffmpeg(*args)
    return out


class Reg:  # pylint: disable=too-few-public-methods  # one-method registry stand-in
    """Registry stand-in returning the scripted backend for a task."""

    def __init__(self, **tasks):
        self.tasks = tasks

    def first(self, task):
        """The backend for `task` or None."""
        return self.tasks.get(task)


class Probe:  # pylint: disable=too-few-public-methods  # one-method port stand-in
    """Transcriber that inspects the wav the extractor hands it, with ffprobe/ffmpeg."""

    def __init__(self):
        self.seen = {}

    def transcribe(self, path, _language=None):
        """Record sample rate/channels/duration and whether the tone survived."""
        path = Path(path)
        out = run("ffprobe", "-v", "error",
                  "-show_entries", "stream=sample_rate,channels,codec_name",
                  "-show_entries", "format=duration", "-of", "default=nw=1", path).stdout.decode()
        self.seen["probe"] = dict(line.split("=") for line in out.split())
        vol = run("ffmpeg", "-i", path, "-af", "volumedetect", "-f", "null", "-").stderr.decode()
        self.seen["volume"] = vol
        return [TimedText(0.0, 4.0, "scripted transcript")]


class Vision:  # pylint: disable=too-few-public-methods  # one-method port stand-in
    """Vision stand-in that inspects the frames the extractor extracted."""

    def __init__(self):
        self.frames = []

    def describe(self, images, _prompt):
        """Record each frame's JPEG magic and its dominant colour (1x1 raw RGB via ffmpeg)."""
        for img in images:
            raw = run("ffmpeg", "-i", img, "-vf", "scale=1:1", "-f", "rawvideo",
                      "-pix_fmt", "rgb24", "-").stdout
            self.frames.append((Path(img).read_bytes()[:2], tuple(raw[:3])))
        return "scripted description"
