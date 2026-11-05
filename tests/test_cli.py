"""CLI round trips through a real subprocess (HOME and INFOPARSER_HOME isolated in tmp_path)."""
import json
import os
import subprocess
import sys

QUOKKA = "Quokkas are small marsupials from Australia."


def _exec(env, *args):
    return subprocess.run([sys.executable, "-m", "infoparser.cli", *args], env=env,
                          capture_output=True, text=True, timeout=60, check=False)


def run(home, *args):
    """Run the CLI against `home`; HOME points beside it so the real ~/InfoParser is never used."""
    env = {**os.environ, "INFOPARSER_HOME": str(home), "HOME": str(home) + "-userhome"}
    return _exec(env, *args)


def test_cli_submit_worker_search_roundtrip(tmp_path):
    """init, submit, worker, search, show, inbox work end to end."""
    home = tmp_path / "h"
    assert run(home, "init").returncode == 0
    r = run(home, "submit", QUOKKA, "--context", "animals")
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
    """Unknown ids give a clean error; --home after the subcommand is honoured."""
    home = tmp_path / "h"
    for args in (("retry", "nope"), ("show", "nope")):
        r = run(home, *args)
        assert r.returncode != 0 and "Traceback" not in r.stderr and "nope" in r.stderr
    fake_home = tmp_path / "fakehome"  # a regression must never touch the real ~/InfoParser
    fake_home.mkdir()
    env = {**{k: v for k, v in os.environ.items() if k != "INFOPARSER_HOME"},
           "HOME": str(fake_home)}
    r = _exec(env, "init", "--home", str(tmp_path / "h2"))
    assert r.returncode == 0 and (tmp_path / "h2" / "infoparser.db").exists()
    assert not (fake_home / "InfoParser").exists()


def test_cli_ask_and_search_citation_format_no_answer_backend(tmp_path):
    """Without an answer backend, ask is retrieval-only and citations are numbered."""
    home = tmp_path / "h"
    run(home, "submit", QUOKKA)
    run(home, "worker", "--once")
    s = run(home, "search", "quokkas", "--mode", "fts")
    assert s.returncode == 0 and s.stdout.startswith("[1] ") and " — " in s.stdout
    a = run(home, "ask", "where do quokkas live?")
    assert a.returncode == 0 and "retrieval-only" in a.stdout and "[1] " in a.stdout
    j = json.loads(run(home, "ask", "quokkas", "--json", "--k", "3").stdout)
    assert j["mode"] == "retrieval-only" and j["interpretation"] is None and j["retrieved"]
    assert run(home, "ask", "zzzqq").returncode == 0


def test_cli_export_backup_verify_restore_digest(tmp_path):
    """export, backup, verify, restore and digest behave and refuse unsafe input."""
    home = tmp_path / "h"
    run(home, "init")
    run(home, "submit", QUOKKA)
    run(home, "worker", "--once")
    e = run(home, "export")
    assert e.returncode == 0 and "exported" in e.stdout and list((home / "vault").rglob("*.md"))
    b = run(home, "backup", str(tmp_path / "bk"))
    assert b.returncode == 0
    arc = b.stdout.split()[-1]
    assert run(home, "verify", arc).returncode == 0
    assert run(home, "restore", arc).returncode != 0  # non-empty home refused
    assert run(tmp_path / "h2", "restore", arc).returncode == 0
    assert "Quokkas" in run(tmp_path / "h2", "search", "quokkas").stdout
    d = run(home, "digest", "--dry-run")
    assert d.returncode == 0 and "Digest" in d.stdout and not (home / "digests").exists()
    d2 = run(home, "digest")
    assert d2.returncode == 0 and list((home / "digests").glob("*.md"))
    assert "already" in run(home, "digest").stdout
    bad = tmp_path / "bad.tar.gz"
    bad.write_bytes(b"not a tar")
    assert run(home, "verify", str(bad)).returncode != 0
