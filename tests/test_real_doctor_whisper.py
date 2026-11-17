"""Real `pith doctor` and a real media submit in an ISOLATED home, with whisper.cpp absent.

Genuine for the degradation path only. Real transcription stays UNVERIFIED: there is no whisper-cli
or model on this machine, and none is downloaded here.
"""
import os
import shutil
import subprocess
import sys

import pytest
from realtools import make_av, needs

pytestmark = pytest.mark.skipif(shutil.which("whisper-cli") is not None,
                                reason="whisper-cli is installed: this is the absent-binary check")


def cli(tmp_path, *args):
    """Run the real CLI in a throwaway HOME (the real home is never touched)."""
    home = tmp_path / "h"
    env = {"HOME": str(home), "PATH": os.environ["PATH"],
           "PITH_HOME": str(home / "Pith")}
    return subprocess.run([sys.executable, "-m", "pith.cli", *args], capture_output=True,
                          text=True, timeout=120, check=False, env=env)


def test_doctor_reports_whisper_missing_as_warning_not_failure(tmp_path):
    """Exit 0; whisper-cli is a WARN line saying it was not found."""
    r = cli(tmp_path, "doctor")
    assert r.returncode == 0
    assert "[WARN ] tool:whisper-cli: 'whisper-cli' not found on PATH" in r.stdout
    assert not (tmp_path / "h" / "Pith" / "infoparser.db").exists()  # doctor creates nothing


@needs("ffmpeg", "ffprobe")
def test_audio_item_degrades_to_needs_clarification_without_whisper(tmp_path):
    """submit -> worker: the item waits for pasted text; no failure, no invented transcript."""
    clip = make_av(tmp_path / "talk.mp4", seconds=2)
    assert cli(tmp_path, "init").returncode == 0
    assert cli(tmp_path, "submit", "--file", str(clip)).returncode == 0
    assert cli(tmp_path, "worker", "--once").returncode == 0
    out = cli(tmp_path, "inbox").stdout
    assert "needs_clarification" in out
