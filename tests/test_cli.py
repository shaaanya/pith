import os
import subprocess
import sys


def run(home, *args):
    env = {**os.environ, "INFOPARSER_HOME": str(home)}
    return subprocess.run([sys.executable, "-m", "infoparser.cli", *args], env=env,
                          capture_output=True, text=True, timeout=60)


def test_cli_submit_worker_search_roundtrip(tmp_path):
    home = tmp_path / "h"
    assert run(home, "init").returncode == 0
    r = run(home, "submit", "Quokkas are small marsupials from Australia.", "--context", "animals")
    assert r.returncode == 0
    iid = r.stdout.split()[-1]
    assert run(home, "worker", "--once").returncode == 0
    s = run(home, "search", "quokkas")
    assert s.returncode == 0 and "Quokkas" in s.stdout
    assert iid in run(home, "show", iid).stdout
    assert "processed" in run(home, "inbox").stdout
    assert "processed" not in run(home, "inbox", "--status", "failed").stdout
    assert run(home, "show", "nope").returncode != 0
    assert run(home, "search", '"foo" AND ( NEAR').returncode == 0
