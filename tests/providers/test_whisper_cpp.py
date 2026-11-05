import sys
from pathlib import Path

import pytest

from infoparser.providers.ports import ProviderError, TimedText
from infoparser.providers.registry import Registry
from infoparser.providers.whisper_cpp import WhisperCppBackend

FAKE = str(Path(__file__).parent.parent / "stubs" / "fake_whisper.py")


@pytest.fixture
def wav(tmp_path):
    p = tmp_path / "a.wav"
    p.write_bytes(b"RIFF")
    return p


def test_whisper_cpp_parses_json_output_via_fake_binary(wav):
    b = WhisperCppBackend("w", FAKE, "model.bin", language="en", threads=2)
    assert b.capabilities.transcribe and b.locality == "local"
    assert b.transcribe(wav) == [TimedText(0.0, 2.5, "Hello there."), TimedText(2.5, 5.0, "General Kenobi.")]
    assert b.transcribe(wav, "de")  # per-call language override accepted


def test_whisper_cpp_errors(tmp_path, wav):
    bad = tmp_path / "fail.wav"
    bad.write_bytes(b"x")
    with pytest.raises(ProviderError, match="boom"):
        WhisperCppBackend("w", FAKE, "m").transcribe(bad)
    with pytest.raises(ProviderError):
        WhisperCppBackend("w", "/no/such/bin", "m").transcribe(wav)
    with pytest.raises(ProviderError):
        WhisperCppBackend("w", FAKE, "m").transcribe(tmp_path / "missing.wav")


def test_whisper_cpp_via_registry_spec(make_cfg, wav):
    r = Registry.from_config(make_cfg({"w": {"type": "whisper_cpp", "binary": FAKE, "model_path": "m"}},
                                      {"transcribe": ["w"]}))
    assert r.first("transcribe").transcribe(wav)[0].text == "Hello there."
    assert "transcribe" in {d["name"]: d for d in r.describe()}["w"]["tasks"]
    with pytest.raises(ValueError, match="'w'"):
        Registry.from_config(make_cfg({"w": {"type": "whisper_cpp", "binary": FAKE}}))
