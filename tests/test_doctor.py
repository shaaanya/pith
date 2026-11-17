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
    assert r["routes"]["distill"]["blocked"] is True and r["routes"]["distill"]["data"]
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
        iid = s.inbox.submit(adapter="t", text="Quokkas are small marsupials from Australia. " * 12).id
        runner.process(s, iid)  # short notes are kept verbatim without a model call
        rows = s.conn.execute("SELECT * FROM processing_events WHERE stage='egress' AND inbox_id=?", (iid,)).fetchall()
        assert rows and all(r["backend"] == "cloud" and r["egress"] == 1 for r in rows)
        assert json.loads(rows[0]["detail"])["bytes_sent"] > 20
        assert stub.requests  # the call really happened
        # local backends leave no egress rows
        cfg2 = cfg_for(tmp_path / "b", backends={"l": {"type": "openai_compat", "base_url": stub.base_url, "model": "m"}},
                       tasks={"distill": ["l"]})
        s2 = build(cfg2)
        i2 = s2.inbox.submit(adapter="t", text="Quokkas are small marsupials from Australia. " * 12).id
        runner.process(s2, i2)
        assert s2.conn.execute("SELECT count(*) FROM processing_events WHERE stage='egress'").fetchone()[0] == 0


def test_egress_blocked_remote_leaves_no_event(tmp_path):
    with OpenAIStub() as stub:
        cfg = cfg_for(tmp_path, allow_remote=False,
                      backends={"cloud": {"type": "openai_compat", "base_url": stub.base_url, "model": "m", "locality": "remote"}},
                      tasks={"distill": ["cloud"]})
        s = build(cfg)
        iid = s.inbox.submit(adapter="t", text="Quokkas are small marsupials from Australia. " * 12).id
        runner.process(s, iid)
        assert not stub.requests
        assert s.conn.execute("SELECT count(*) FROM processing_events WHERE stage='egress'").fetchone()[0] == 0


def _server(handler_cls):
    import threading
    from http.server import ThreadingHTTPServer
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_probe_timeout_is_enforced_against_a_server_that_never_answers(tmp_path, monkeypatch):
    import socket
    import threading
    import time
    ls = socket.socket()
    ls.bind(("127.0.0.1", 0))
    ls.listen()
    held = []
    threading.Thread(target=lambda: held.append(ls.accept()), daemon=True).start()
    monkeypatch.setattr(doctor, "PROBE_TIMEOUT", 0.4)
    cfg = cfg_for(tmp_path, backends={"slow": {"type": "openai_compat", "base_url": f"http://127.0.0.1:{ls.getsockname()[1]}/v1", "model": "m"}})
    t = time.time()
    checks = doctor.run(cfg)
    ls.close()
    assert time.time() - t < 3 and by(checks, "backend:slow").level == "WARN"


def test_probe_sends_configured_key_and_401_is_not_called_unreachable(tmp_path, monkeypatch):
    from http.server import BaseHTTPRequestHandler
    got = []

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            got.append(self.headers.get("Authorization"))
            ok = self.headers.get("Authorization") == "Bearer probe-credential-xyz"
            self.send_response(200 if ok else 401)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")
    srv = _server(H)
    try:
        spec = {"type": "openai_compat", "base_url": f"http://127.0.0.1:{srv.server_port}/v1", "model": "m", "api_key_env": "IP_DOC_KEY"}
        monkeypatch.setenv("IP_DOC_KEY", "probe-credential-xyz")
        c = by(doctor.run(cfg_for(tmp_path, backends={"k": spec})), "backend:k")
        assert c.level == "OK" and "probe-credential-xyz" not in c.detail and got[-1] == "Bearer probe-credential-xyz"
        monkeypatch.delenv("IP_DOC_KEY")
        c = by(doctor.run(cfg_for(tmp_path, backends={"k": spec})), "backend:k")
        assert "unreachable" not in c.detail and "auth required" in c.detail
    finally:
        srv.shutdown()
        srv.server_close()


def test_egress_sink_failure_is_fail_open_and_wrap_is_single(tmp_path, capsys):
    from infoparser.providers import egress
    with OpenAIStub() as stub:
        cfg = cfg_for(tmp_path, allow_remote=True,
                      backends={"cloud": {"type": "openai_compat", "base_url": stub.base_url, "model": "m", "locality": "remote"}},
                      tasks={"distill": ["cloud"]})
        s = build(cfg)
        b = s.registry.backends["cloud"]
        g = b.generate
        assert egress.wrap_remote(b) is b and b.generate is g  # second wrap is a no-op
        s.conn.execute("CREATE TRIGGER no_egress BEFORE INSERT ON processing_events WHEN NEW.stage='egress'"
                       " BEGIN SELECT RAISE(ABORT, 'audit disk full'); END")  # only the audit insert fails
        egress._warned = False
        iid_row = s.inbox.submit(adapter="t", text="Quokkas are small marsupials from Australia. " * 12)
        runner.process(s, iid_row.id)
        assert stub.requests  # the backend call still went out
        assert capsys.readouterr().err.count("egress audit write failed") == 1


def test_every_port_method_is_wrapped():
    import inspect
    from infoparser.providers import egress, ports
    names = {n for _, c in inspect.getmembers(ports, inspect.isclass) if getattr(c, "_is_protocol", False) and c is not ports.Backend
             for n, f in vars(c).items() if callable(f) and not n.startswith("_")}
    assert names and names <= set(egress.METHODS)
