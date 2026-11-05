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


def test_cli_unknown_id_clean_error_and_flags_after_subcommand(tmp_path):
    home = tmp_path / "h"
    for args in (("retry", "nope"), ("show", "nope")):
        r = run(home, *args)
        assert r.returncode != 0 and "Traceback" not in r.stderr and "nope" in r.stderr
    env = {k: v for k, v in os.environ.items() if k != "INFOPARSER_HOME"}
    r = subprocess.run([sys.executable, "-m", "infoparser.cli", "init", "--home", str(tmp_path / "h2")],
                       env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and (tmp_path / "h2" / "infoparser.db").exists()


def test_cli_ask_and_search_citation_format_no_answer_backend(tmp_path):
    import json
    home = tmp_path / "h"
    run(home, "submit", "Quokkas are small marsupials from Australia.")
    run(home, "worker", "--once")
    s = run(home, "search", "quokkas", "--mode", "fts")
    assert s.returncode == 0 and s.stdout.startswith("[1] ") and " — " in s.stdout
    a = run(home, "ask", "where do quokkas live?")
    assert a.returncode == 0 and "retrieval-only" in a.stdout and "[1] " in a.stdout
    j = json.loads(run(home, "ask", "quokkas", "--json", "--k", "3").stdout)
    assert j["mode"] == "retrieval-only" and j["interpretation"] is None and j["retrieved"]
    assert run(home, "ask", "zzzqq").returncode == 0
