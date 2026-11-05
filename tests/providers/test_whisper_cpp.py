"""whisper.cpp backend against a fake binary."""
import sys
from pathlib import Path

import pytest

from infoparser.providers.ports import ProviderError, TimedText
from infoparser.providers.registry import Registry
from infoparser.providers.whisper_cpp import WhisperCppBackend

FAKE = str(Path(__file__).parent.parent / "stubs" / "fake_whisper.py")


@pytest.fixture(name="wav")
def wav_fixture(tmp_path):
    """A placeholder wav file."""
    p = tmp_path / "a.wav"
    p.write_bytes(b"RIFF....WAVE")
    return p


def test_whisper_cpp_parses_json_output_via_fake_binary(wav):
    """JSON output of the (fake) binary becomes timed segments."""
    b = WhisperCppBackend("w", FAKE, "model.bin", language="en", threads=2)
    assert b.capabilities.transcribe and b.locality == "local"
    assert b.transcribe(wav) == [TimedText(0.0, 2.5, "Hello there."),
                                 TimedText(2.5, 5.0, "General Kenobi.")]
    assert b.transcribe(wav, "de")  # per-call language override accepted


def test_whisper_cpp_errors(tmp_path, wav):
    """Bad exit, missing binary and missing file are ProviderErrors."""
    bad = tmp_path / "fail.wav"
    bad.write_bytes(b"RIFF....WAVE")
    with pytest.raises(ProviderError, match="boom"):
        WhisperCppBackend("w", FAKE, "m").transcribe(bad)
    with pytest.raises(ProviderError):
        WhisperCppBackend("w", "/no/such/bin", "m").transcribe(wav)
    with pytest.raises(ProviderError):
        WhisperCppBackend("w", FAKE, "m").transcribe(tmp_path / "missing.wav")


def test_whisper_cpp_via_registry_spec(make_cfg, wav):
    """Built from a registry spec; incomplete specs are rejected."""
    spec = {"w": {"type": "whisper_cpp", "binary": FAKE, "model_path": "m"}}
    r = Registry.from_config(make_cfg(spec, {"transcribe": ["w"]}))
    assert r.first("transcribe").transcribe(wav)[0].text == "Hello there."
    assert "transcribe" in {d["name"]: d for d in r.describe()}["w"]["tasks"]
    with pytest.raises(ValueError, match="'w'"):
        Registry.from_config(make_cfg({"w": {"type": "whisper_cpp", "binary": FAKE}}))


def test_whisper_cpp_timestamps_only_json(tmp_path):
    """Older JSON with only timestamp strings still parses."""
    p = tmp_path / "ts.wav"
    p.write_bytes(b"RIFF....WAVE")
    got = WhisperCppBackend("w", FAKE, "m").transcribe(p)
    assert got == [TimedText(1.5, 62.25, "From stamps.")]


def test_whisper_cpp_rejects_non_wav_input(tmp_path):
    """Non-wav input is refused up front."""
    mp3 = tmp_path / "a.wav"
    mp3.write_bytes(b"ID3\x03\x00\x00")
    with pytest.raises(ProviderError, match="16 kHz mono wav"):
        WhisperCppBackend("w", FAKE, "m").transcribe(mp3)


def test_whisper_cpp_non_utf8_output_is_provider_error_not_unicode_error(tmp_path):
    """Non-UTF-8 process output maps to ProviderError."""
    exe = tmp_path / "bad"
    exe.write_text(f"#!{sys.executable}\nimport sys\nsys.stderr.buffer.write(b'\\xff\\xfe oops')\n"
                   "sys.stdout.buffer.write(b'\\xff')\nsys.exit(2)\n")
    exe.chmod(0o755)
    w = tmp_path / "x.wav"
    w.write_bytes(b"RIFF....WAVE")
    with pytest.raises(ProviderError, match="exit 2"):
        WhisperCppBackend("w", str(exe), "m").transcribe(w)
