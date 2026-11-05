import json
import os
import subprocess
import sys

from infoparser import doctor
from infoparser.config import Config
from infoparser.pipeline import runner
from infoparser.services import build
from stubs.openai_stub import OpenAIStub

MARK = "ZXQ-SECRET-MARKER-98127"


def cfg_for(tmp_path, backends=None, tasks=None, allow_remote=False, **kw):
    home = tmp_path / "home"
    return Config(home=home, db_path=home / "infoparser.db", blobs_dir=home / "blobs", vault_dir=home / "vault",
                  backends=backends or {}, tasks=tasks or {}, allow_remote=allow_remote, **kw)


def by(checks, name):
    return next(c for c in checks if c.name == name)


def cli(home, *args):
    env = {**os.environ, "INFOPARSER_HOME": str(home)}
    return subprocess.run([sys.executable, "-m", "infoparser.cli", *args], env=env, capture_output=True, text=True, timeout=60)


def test_doctor_on_empty_home_reports_and_creates_nothing(tmp_path):
    cfg = cfg_for(tmp_path)
    checks = doctor.run(cfg)
    assert not cfg.home.exists()  # read-only: never creates the home or the db
    assert by(checks, "python").level == "OK" and by(checks, "sqlite_fts5").level == "OK"
    assert by(checks, "database").level == "WARN" and "not initialized" in by(checks, "database").detail
    assert doctor.exit_code(checks) == 0


def test_doctor_on_corrupted_db_no_traceback(tmp_path):
    cfg = cfg_for(tmp_path)
    cfg.home.mkdir()
    cfg.db_path.write_bytes(b"this is not a sqlite database" * 100)
    checks = doctor.run(cfg)
    db = by(checks, "database")
    assert db.level == "ERROR" and doctor.exit_code(checks) == 1
    r = cli(cfg.home, "doctor")
    assert r.returncode == 1 and "Traceback" not in r.stderr + r.stdout and "database" in r.stdout


def test_doctor_json_is_valid_and_exit_codes(tmp_path):
    r = cli(tmp_path / "h", "doctor", "--json")
    out = json.loads(r.stdout)
    assert r.returncode == 0 and out["ok"] is True and {"name", "level", "detail"} <= set(out["checks"][0])
    (tmp_path / "bad").mkdir()
    (tmp_path / "bad" / "infoparser.db").write_bytes(b"garbage" * 1000)
    r = cli(tmp_path / "bad", "doctor", "--json")
    assert r.returncode == 1 and json.loads(r.stdout)["ok"] is False


def test_doctor_reports_missing_binary_not_crash(tmp_path):
    cfg = cfg_for(tmp_path, yt_dlp_binary="/no/such/yt-dlp", ffmpeg_binary="/no/such/ffmpeg",
                  backends={"o": {"type": "tesseract", "binary": "/no/such/tesseract"},
                            "w": {"type": "whisper_cpp", "binary": "/no/such/whisper", "model_path": "/no/model"}})
    checks = doctor.run(cfg)
    assert by(checks, "tool:yt-dlp").level == "WARN" and "not found" in by(checks, "tool:yt-dlp").detail
    assert by(checks, "backend:o").level == "WARN" and by(checks, "backend:w").level == "WARN"
    assert doctor.exit_code(checks) == 0


def test_doctor_bad_config_is_an_error_not_a_traceback(tmp_path):
    checks = doctor.run(cfg_for(tmp_path, backends={"x": {"type": "nope"}}))
    assert by(checks, "backends").level == "ERROR"


def test_doctor_healthy_db_blob_integrity_and_orphans(svc):
    svc.inbox.submit(adapter="t", file=b"blobby content", filename="a.bin")
    runner.process(svc, svc.inbox.list()[0]["id"])
    checks = doctor.run(svc.cfg, full=True)
    assert by(checks, "database").level == "OK" and by(checks, "blobs").level == "OK"
    orphan = svc.blobs.put_bytes(b"nobody references me")
    assert by(doctor.run(svc.cfg, full=True), "orphans").level == "WARN"
    svc.blobs.path(orphan).unlink()
    ref = svc.conn.execute("SELECT blob_sha256 FROM inbox_items WHERE blob_sha256 IS NOT NULL").fetchone()[0]
    svc.blobs.path(ref).write_bytes(b"tampered")
    assert by(doctor.run(svc.cfg, full=True), "blobs").level == "ERROR"


def test_doctor_permissions(svc):
    svc.cfg.home.chmod(0o755)
    (svc.cfg.home / "http_token").write_text("t")
    (svc.cfg.home / "http_token").chmod(0o644)
    c = doctor.run(svc.cfg)
    assert by(c, "permissions").level == "WARN"


def test_doctor_never_sends_user_content_and_probes_stub(tmp_path):
    with OpenAIStub() as stub:
        cfg = cfg_for(tmp_path, backends={"l": {"type": "openai_compat", "base_url": stub.base_url, "model": "m",
                                                "embed_model": "e"}})
        s = build(cfg)
        s.inbox.submit(adapter="t", text=f"private {MARK} note about quokkas")
        runner.process(s, s.inbox.list()[0]["id"])
        n_before = len(stub.requests)
        checks = doctor.run(cfg)
        assert by(checks, "backend:l").level == "OK" and "reachable" in by(checks, "backend:l").detail
        for path, headers, body in stub.requests[n_before:]:
            assert MARK.encode() not in body and "quokkas" not in body.decode(errors="replace")
        assert MARK not in json.dumps([c.__dict__ for c in checks], default=str)


def test_doctor_unreachable_backend_fast_and_remote_not_probed(tmp_path):
    import time
    cfg = cfg_for(tmp_path, backends={
        "dead": {"type": "openai_compat", "base_url": "http://127.0.0.1:9/v1", "model": "m"},
        "cloud": {"type": "openai_compat", "base_url": "http://127.0.0.1:9/v1", "model": "m", "locality": "remote"}})
    t = time.time()
    checks = doctor.run(cfg)
    assert time.time() - t < 8
    assert by(checks, "backend:dead").level == "WARN" and "unreachable" in by(checks, "backend:dead").detail
    assert "not probed" in by(checks, "backend:cloud").detail


def test_egress_report_states_routes_and_limits(tmp_path):
    cfg = cfg_for(tmp_path, backends={"cloud": {"type": "openai_compat", "base_url": "https://api.example.com/v1",
                                                "model": "m", "locality": "remote"}},
                  tasks={"distill": ["cloud"]})
    r = doctor.egress_report(cfg)
    assert r["allow_remote"] is False and r["routes"]["distill"]["remote"] == ["cloud"]
    assert r["routes"]["distill"]["blocked"] is True and "what leaves" in " ".join(r["routes"]["distill"]) or r["routes"]["distill"]["data"]
    assert "cannot report what a remote provider logs" in r["note"]
    cfg.allow_remote = True
    r = doctor.egress_report(cfg)
    assert r["routes"]["distill"]["blocked"] is False
    out = cli(tmp_path / "x", "egress")
    assert out.returncode == 0 and "cannot report" in out.stdout


def test_egress_event_logged_for_remote_backend(tmp_path):
    with OpenAIStub() as stub:
        cfg = cfg_for(tmp_path, allow_remote=True,
                      backends={"cloud": {"type": "openai_compat", "base_url": stub.base_url, "model": "m",
                                          "locality": "remote"}},
                      tasks={"distill": ["cloud"]})
        s = build(cfg)
        iid = s.inbox.submit(adapter="t", text="Quokkas are small marsupials from Australia.").id
        runner.process(s, iid)
        rows = s.conn.execute("SELECT * FROM processing_events WHERE stage='egress' AND inbox_id=?", (iid,)).fetchall()
        assert rows and all(r["backend"] == "cloud" and r["egress"] == 1 for r in rows)
        assert json.loads(rows[0]["detail"])["bytes_sent"] > 20
        assert stub.requests  # the call really happened
        # local backends leave no egress rows
        cfg2 = cfg_for(tmp_path / "b", backends={"l": {"type": "openai_compat", "base_url": stub.base_url, "model": "m"}},
                       tasks={"distill": ["l"]})
        s2 = build(cfg2)
        i2 = s2.inbox.submit(adapter="t", text="Quokkas are small marsupials from Australia.").id
        runner.process(s2, i2)
        assert s2.conn.execute("SELECT count(*) FROM processing_events WHERE stage='egress'").fetchone()[0] == 0


def test_egress_blocked_remote_leaves_no_event(tmp_path):
    with OpenAIStub() as stub:
        cfg = cfg_for(tmp_path, allow_remote=False,
                      backends={"cloud": {"type": "openai_compat", "base_url": stub.base_url, "model": "m", "locality": "remote"}},
                      tasks={"distill": ["cloud"]})
        s = build(cfg)
        iid = s.inbox.submit(adapter="t", text="Quokkas are small marsupials from Australia.").id
        runner.process(s, iid)
        assert not stub.requests
        assert s.conn.execute("SELECT count(*) FROM processing_events WHERE stage='egress'").fetchone()[0] == 0
