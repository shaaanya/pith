import datetime as dt

import pytest

from pith import digest
from pith.pipeline import runner

TODAY = dt.date(2026, 11, 5)
NOW = dt.datetime(2026, 11, 5, 9, 0, tzinfo=dt.UTC)


def load(svc, notes):
    ids = []
    for t in notes:
        ids.append(svc.inbox.submit(adapter="t", text=t).id)
        runner.process(svc, ids[-1])
    return ids


def age(svc, days):
    old = (NOW - dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    svc.conn.execute("UPDATE knowledge_items SET created_at=?", (old,))


def test_digest_sections(svc):
    load(svc, [f"Old fact number {i} about topic{i} things." for i in range(8)])
    age(svc, 30)
    a, b = load(svc, ["Fresh note about quokkas on Rottnest Island.", "Another fresh note about quokkas on Rottnest."])
    ia, ib = [r["id"] for r in svc.conn.execute("SELECT id FROM knowledge_items WHERE created_at>? ORDER BY id", ("2026-11-04",))][:2]
    svc.conn.execute("DELETE FROM relations")
    svc.conn.execute("INSERT INTO relations(item_a,item_b,type,score) VALUES (?,?,'duplicate',0.97)", (ia, ib))
    bad = svc.inbox.submit(adapter="t", text="https://example.invalid/x").id
    svc.inbox.set_status(bad, "failed", "HTTP 404")
    nc = svc.inbox.submit(adapter="t", text="https://example.invalid/y").id
    svc.inbox.set_status(nc, "needs_clarification", "paste the text")
    d = digest.data(svc, now=NOW, since_days=7, seed="s")
    assert d["new"]["total"] >= 1 and {i["title"] for i in d["new"]["items"]}
    assert {a["id"] for a in d["attention"]} == {bad, nc}
    assert 1 <= len(d["resurfaced"]) <= 5
    md = digest.build(svc, since_days=7, now=NOW, seed="s")
    for h in ("## New", "## Needs attention", "## Worth revisiting", "## Possible duplicates"):
        assert h in md
    assert "None found" not in md.split("## Possible duplicates")[1] and "0.97" in md
    assert "HTTP 404" in md and "quokkas" in md.lower()


def test_resurfacing_deterministic_with_seed_and_capped(svc):
    load(svc, [f"Old fact number {i} about topic{i} things." for i in range(12)])
    age(svc, 30)
    a = digest.build(svc, now=NOW, seed="x")
    assert a == digest.build(svc, now=NOW, seed="x")
    assert a.count("\n- ") <= 5 + 1 + 20  # resurfaced capped at 5
    assert len(digest.data(svc, now=NOW, seed="x")["resurfaced"]) == 5
    assert digest.data(svc, now=NOW, seed="y")["resurfaced"] != digest.data(svc, now=NOW, seed="x")["resurfaced"]


def test_max_items_caps_new_section(svc):
    load(svc, [f"Fresh distinct note {i} number {i * 7}." for i in range(6)])
    d = digest.data(svc, now=NOW, since_days=7, max_items=2)
    assert len(d["new"]["items"]) == 2 and d["new"]["total"] >= 6


def test_interval_once_per_period_and_dry_run_writes_nothing(svc):
    load(svc, ["Fresh note about quokkas."])
    r = digest.run(svc, dry_run=True, today=TODAY, now=NOW)
    assert r.path is None and not list(svc.cfg.home.glob("digests/*")) and "quokkas" in r.text.lower()
    r1 = digest.run(svc, today=TODAY, now=NOW)
    assert r1.path == svc.cfg.home / "digests" / "2026-11-05.md" and r1.path.read_text() == r1.text and not r1.skipped
    r2 = digest.run(svc, today=TODAY + dt.timedelta(days=2), now=NOW)
    assert r2.skipped and "already" in r2.text and len(list((svc.cfg.home / "digests").glob("*.md"))) == 1
    age(svc, 1)  # the note now predates the last digest
    r3 = digest.run(svc, today=TODAY + dt.timedelta(days=7), now=NOW + dt.timedelta(days=7))
    assert not r3.skipped and r3.path.name == "2026-11-12.md"
    assert "quokkas" not in r3.text.lower().split("## worth revisiting")[0]  # only items since the last digest are new


def test_since_override(svc):
    load(svc, ["Fresh note about quokkas."])
    digest.run(svc, today=TODAY, now=NOW)
    r = digest.run(svc, since="2026-11-01", dry_run=True, today=TODAY + dt.timedelta(days=1), now=NOW)
    assert not r.skipped and "quokkas" in r.text.lower()


def test_empty_library_is_friendly(svc):
    r = digest.run(svc, dry_run=True, today=TODAY, now=NOW)
    assert "empty" in r.text.lower() and "Traceback" not in r.text and len(r.text) < 600
    assert r.path is None
    written = digest.run(svc, today=TODAY, now=NOW)
    assert written.path.exists()


def test_hostile_title_cannot_break_markdown_structure(svc):
    load(svc, ["Some fresh note."])
    svc.conn.execute("UPDATE knowledge_items SET title='x\n## Injected heading\n[a](javascript:alert(1))'")
    md = digest.build(svc, now=NOW)
    assert "\n## Injected" not in md


@pytest.mark.parametrize("bad", ["abc", "-3", "2026-13-45", "nan", "inf", "99999999", "2026-02-30"])
def test_bad_since_is_a_clean_error(svc, bad):
    with pytest.raises(ValueError):
        digest.run(svc, since=bad, dry_run=True, today=TODAY, now=NOW)


def test_cli_bad_since_clean_exit(tmp_path):
    import os
    import subprocess
    import sys
    env = {**os.environ, "PITH_HOME": str(tmp_path / "h")}
    r = subprocess.run([sys.executable, "-m", "pith.cli", "digest", "--since", "2026-13-45"], env=env, capture_output=True, text=True)
    assert r.returncode != 0 and "error:" in r.stderr and "Traceback" not in r.stderr


def test_since_does_not_overwrite_todays_digest_or_bypass_interval(svc):
    load(svc, ["Fresh note about quokkas."])
    r1 = digest.run(svc, today=TODAY, now=NOW)
    first = r1.path.read_text()
    r2 = digest.run(svc, since="2026-01-01", today=TODAY, now=NOW)
    assert r2.skipped and "--force" in r2.text and r1.path.read_text() == first
    r3 = digest.run(svc, since="2026-01-01", today=TODAY, now=NOW, force=True)
    assert not r3.skipped and r3.path == r1.path
