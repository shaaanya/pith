"""Transcription via whisper.cpp's CLI. UNVERIFIED against a real whisper-cli binary (none installed
here); tested only with tests/stubs/fake_whisper.py, which mimics the documented flags and JSON.

Command: <binary> -m <model_path> -f <wav> -oj -of <tmpprefix> [-l <lang>] [-t <threads>]
-oj writes <tmpprefix>.json: {"transcription": [{"offsets": {"from": ms, "to": ms}, "text": ...}]}
("timestamps" "HH:MM:SS,mmm" strings are used as a fallback).
Input must be a 16 kHz mono wav; the caller converts (the media extractor already does, via ffmpeg),
so this backend does not shell out to ffmpeg itself.

Spec keys: type = "whisper_cpp"; binary (required); model_path (required); language (optional,
whisper code; per-call `language` overrides); threads (optional int); timeout (seconds, 3600).
"""
import json
import subprocess
import tempfile
from pathlib import Path

from .ports import Capabilities, ProviderError, TimedText


def _ts(s: str) -> float:
    h, m, rest = s.replace(",", ".").split(":")
    return int(h) * 3600 + int(m) * 60 + float(rest)


class WhisperCppBackend:
    locality = "local"
    capabilities = Capabilities(transcribe=True)

    def __init__(self, name, binary, model_path, language=None, threads=None, timeout=3600):
        self.name, self.binary, self.model_path = name, binary, str(model_path)
        self.language, self.threads, self.timeout = language, threads, timeout

    @classmethod
    def from_spec(cls, name, spec):
        return cls(name, spec["binary"], spec["model_path"], spec.get("language"), spec.get("threads"),
                   spec.get("timeout", 3600))

    def transcribe(self, path: Path, language: str | None = None) -> list[TimedText]:
        path = Path(path)
        if not path.is_file():
            raise ProviderError(f"{self.name}: audio file not found: {path}")
        lang = language or self.language
        with tempfile.TemporaryDirectory() as tmp:
            prefix = str(Path(tmp) / "out")
            argv = [self.binary, "-m", self.model_path, "-f", str(path), "-oj", "-of", prefix]
            if lang:
                argv += ["-l", lang]
            if self.threads:
                argv += ["-t", str(self.threads)]
            try:
                p = subprocess.run(argv, capture_output=True, text=True, timeout=self.timeout)
            except (OSError, subprocess.TimeoutExpired) as e:
                raise ProviderError(f"{self.name}: {e}") from e
            if p.returncode != 0:
                raise ProviderError(f"{self.name}: exit {p.returncode}: {p.stderr.strip()[:300]}")
            try:
                data = json.loads(Path(prefix + ".json").read_text())
                out = []
                for seg in data["transcription"]:
                    if "offsets" in seg:
                        a, b = seg["offsets"]["from"] / 1000, seg["offsets"]["to"] / 1000
                    else:
                        a, b = _ts(seg["timestamps"]["from"]), _ts(seg["timestamps"]["to"])
                    if seg["text"].strip():
                        out.append(TimedText(a, b, seg["text"].strip()))
                return out
            except (OSError, ValueError, KeyError, TypeError) as e:
                raise ProviderError(f"{self.name}: unparseable whisper output ({type(e).__name__}: {e})") from e
