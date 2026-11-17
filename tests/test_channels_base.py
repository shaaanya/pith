"""Channel protocol pieces: per-channel state and the generic run loop."""
import threading

from pith.adapters.base import ChannelState, run_channel


def test_state_roundtrip(svc):
    a, b = ChannelState(svc.conn, "a"), ChannelState(svc.conn, "b")
    assert a.get("k") is None
    assert a.get("k", "d") == "d"
    a.set("k", "1")
    a.set("k", "2")
    assert a.get("k") == "2"
    assert b.get("k") is None


class Fake:
    """Returns/raises the queued results one per poll; sets stop after the last one."""
    name = "fake"
    interval = 0.01

    def __init__(self, results, stop, state=None):
        self.results, self.stop, self.state, self.errors_seen = list(results), stop, state, []

    def poll(self):
        if self.state:
            self.errors_seen.append(self.state.get("last_error"))
        r = self.results.pop(0)
        if not self.results:
            self.stop.set()
        if isinstance(r, Exception):
            raise r
        return r


def test_run_channel_records_ok_and_total(svc):
    stop, st = threading.Event(), ChannelState(svc.conn, "fake")
    run_channel(Fake([2], stop), st, stop)
    assert st.get("submitted") == "2"
    assert st.get("last_ok_at")
    assert st.get("last_error") == ""


def test_run_channel_survives_errors_with_backoff(svc):
    stop, st = threading.Event(), ChannelState(svc.conn, "fake")
    ch = Fake([RuntimeError("boom"), RuntimeError("boom2"), 1], stop, st)
    run_channel(ch, st, stop, max_backoff=0.05)
    assert "boom" in ch.errors_seen[1] and "boom2" in ch.errors_seen[2]
    assert st.get("last_error") == ""
    assert st.get("submitted") == "1"


def test_run_channel_error_is_recorded_when_stopped_mid_failure(svc):
    stop, st = threading.Event(), ChannelState(svc.conn, "fake")
    run_channel(Fake([RuntimeError("nope")], stop), st, stop, max_backoff=0.05)
    assert "nope" in st.get("last_error")
    assert st.get("last_ok_at") is None


def test_run_channel_logs_errors_so_a_foreground_run_shows_them(svc, caplog):
    stop, st = threading.Event(), ChannelState(svc.conn, "fake")
    with caplog.at_level("WARNING"):
        run_channel(Fake([RuntimeError("no token")], stop), st, stop, max_backoff=0.05)
    assert "fake" in caplog.text and "no token" in caplog.text
