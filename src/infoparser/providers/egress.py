"""Egress accounting for remote backends. Remote backends' public call methods are wrapped (in
place, so object identity is kept) to report "backend X is about to receive N bytes" to a
per-context sink BEFORE the call: text leaves even when the call then fails. The runner installs
a sink that writes a processing_events row (stage='egress', backend, egress=1,
detail={"bytes_sent": N}) for the inbox item being processed. ask/search have no inbox item
(processing_events.inbox_id is NOT NULL), so they report egress inline instead (Answer.egress /
SearchResult.egress). Only configured routes can be reported, never what a provider logs."""
import contextlib
import functools
import inspect
import sys
from contextvars import ContextVar
from pathlib import Path

from . import ports

sink: ContextVar = ContextVar("egress_sink", default=None)
_warned = False  # pylint: disable=invalid-name  # mutable module state (tests reset it)
_MARK = "_egress_wrapped"  # attribute set on wrapped methods so they are never wrapped twice


def _port_methods() -> tuple:
    """Public call methods of every port Protocol, so a new port method is wrapped automatically."""
    return tuple(sorted({n for _, c in inspect.getmembers(ports, inspect.isclass)
                         if getattr(c, "_is_protocol", False) and c is not ports.Backend
                         for n, f in vars(c).items() if callable(f) and not n.startswith("_")}))


METHODS = _port_methods()


def warn_once(msg: str) -> None:
    """Print `msg` to stderr the first time only."""
    global _warned  # pylint: disable=global-statement  # process-wide once-flag
    if not _warned:
        _warned = True
        print(msg, file=sys.stderr)


def _file_size(p: Path) -> int:
    """Size of the file in bytes, 0 if it cannot be stat-ed."""
    try:
        return p.stat().st_size
    except OSError:
        return 0


def size_of(o) -> int:
    """Approximate bytes `o` would send: encoded text, raw bytes, file sizes, nested containers."""
    if isinstance(o, str):
        return len(o.encode("utf-8", "replace"))
    if isinstance(o, bytes | bytearray):
        return len(o)
    if isinstance(o, Path):
        return _file_size(o)
    if isinstance(o, dict):
        return sum(size_of(k) + size_of(v) for k, v in o.items())
    if isinstance(o, list | tuple | set):
        return sum(size_of(x) for x in o)
    return len(str(o)) if o is not None else 0


def wrap_remote(b):
    """Wrap each public port method of backend `b` in place to report bytes to the sink."""
    for m in METHODS:
        fn = getattr(b, m, None)
        if not callable(fn) or getattr(fn, _MARK, False):  # never double-wrap
            continue

        def make(fn):
            @functools.wraps(fn)
            def inner(*a, **k):
                if (s := sink.get()) is not None:
                    s(b.name, size_of(a) + size_of(k))
                return fn(*a, **k)
            setattr(inner, _MARK, True)
            return inner
        setattr(b, m, make(fn))
    return b


@contextlib.contextmanager
def collect():
    """Total bytes sent per remote backend by the code inside the block (for commands that have
    no inbox item to attach egress rows to, such as `reindex`)."""
    sent: dict[str, int] = {}
    token = sink.set(lambda name, n: sent.__setitem__(name, sent.get(name, 0) + n))
    try:
        yield sent
    finally:
        sink.reset(token)
