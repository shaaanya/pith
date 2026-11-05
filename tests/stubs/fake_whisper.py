#!/usr/bin/env python3
"""Fake whisper.cpp CLI: honors -m/-f/-of/-oj/-l/-t like whisper-cli, writes <of>.json."""
import json
import sys
from pathlib import Path

a = sys.argv[1:]
opt = {a[i]: a[i + 1] for i in range(len(a) - 1) if a[i] in ("-m", "-f", "-of", "-l", "-t")}
if "-oj" not in a or "-m" not in opt or "-f" not in opt or "-of" not in opt:
    sys.exit("bad args: " + " ".join(a))
if opt["-f"].endswith("fail.wav"):
    sys.exit("boom")
if opt["-f"].endswith("ts.wav"):  # older whisper.cpp JSON: only "timestamps" strings
    segs = [{"timestamps": {"from": "00:00:01,500", "to": "00:01:02,250"}, "text": " From stamps."}]
    Path(opt["-of"] + ".json").write_text(json.dumps({"transcription": segs}), encoding="utf-8")
    sys.exit(0)
out = {"result": {"language": opt.get("-l", "en")}, "transcription": [
    {"timestamps": {"from": "00:00:00,000", "to": "00:00:02,500"},
     "offsets": {"from": 0, "to": 2500}, "text": " Hello there."},
    {"timestamps": {"from": "00:00:02,500", "to": "00:00:05,000"},
     "offsets": {"from": 2500, "to": 5000}, "text": " General Kenobi."}]}
Path(opt["-of"] + ".json").write_text(json.dumps(out), encoding="utf-8")
