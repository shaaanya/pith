#!/usr/bin/env python3
"""Fake yt-dlp CLI for tests (no network). Mimics only the flags InfoParser uses:
  --dump-json ... -- URL                       -> prints tests/fixtures/info.json
  --skip-download --write-subs -o TPL ... -- URL -> writes <TPL minus .%(ext)s>.en.vtt (mode "captions")
  -x ... -o TPL -- URL                         -> writes a silent wav (audio download)
  -f ... -o TPL -- URL (no -x)                 -> copies $FAKE_YTDLP_VIDEO (video download)
Env: FAKE_YTDLP_LOG=file (one JSON line of argv per call), FAKE_YTDLP_MODE=captions|nocaptions|login|fail|hang."""
import json
import os
import shutil
import sys
import time
import wave
from pathlib import Path

FIX = Path(__file__).resolve().parent.parent / "fixtures"
argv = sys.argv[1:]
if os.environ.get("FAKE_YTDLP_LOG"):
    with open(os.environ["FAKE_YTDLP_LOG"], "a") as f:
        f.write(json.dumps(argv) + "\n")
mode = os.environ.get("FAKE_YTDLP_MODE", "captions")
if mode == "hang":
    time.sleep(30)
if mode == "login":
    print("ERROR: [Instagram] abc: login required; rate-limit reached. Use --cookies", file=sys.stderr)
    sys.exit(1)
if mode == "fail":
    print("ERROR: Unable to download webpage: HTTP Error 404: Not Found", file=sys.stderr)
    sys.exit(1)
assert "--" in argv and argv.index("--") == len(argv) - 2, "URL must follow a lone --"
tpl = argv[argv.index("-o") + 1] if "-o" in argv else None
base = tpl[: -len(".%(ext)s")] if tpl else None
if "--dump-json" in argv:
    print((FIX / "info.json").read_text())
elif "--write-subs" in argv:
    if mode == "captions":
        shutil.copy(FIX / "sample.en.vtt", f"{base}.en.vtt")
elif "-x" in argv:
    with wave.open(f"{base}.wav", "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(b"\0\0" * 1600)
else:
    shutil.copy(os.environ["FAKE_YTDLP_VIDEO"], f"{base}.mp4")
