"""Egress accounting for remote backends. Remote backends' public call methods are wrapped (in place, so
object identity is kept) to report "backend X is about to receive N bytes" to a per-context sink BEFORE the call:
text leaves even when the call then fails. The runner installs a sink that writes a processing_events row
(stage='egress', backend, egress=1, detail={"bytes_sent": N}) for the inbox item being processed.
ask/search have no inbox item (processing_events.inbox_id is NOT NULL), so they report egress inline instead
(Answer.egress / SearchResult.egress). Only configured routes can be reported, never what a provider logs."""
import functools
from contextvars import ContextVar
from pathlib import Path

sink: ContextVar = ContextVar("egress_sink", default=None)
METHODS = ("generate", "embed", "rerank", "describe", "read", "transcribe")


def size_of(o) -> int:
    if isinstance(o, str):
        return len(o.encode("utf-8", "replace"))
    if isinstance(o, bytes | bytearray):
        return len(o)
    if isinstance(o, Path):
        try:
            return o.stat().st_size
        except OSError:
            return 0
    if isinstance(o, dict):
        return sum(size_of(k) + size_of(v) for k, v in o.items())
    if isinstance(o, list | tuple | set):
        return sum(size_of(x) for x in o)
    return len(str(o)) if o is not None else 0


def wrap_remote(b):
    for m in METHODS:
        fn = getattr(b, m, None)
        if not callable(fn):
            continue

        def make(fn):
            @functools.wraps(fn)
            def inner(*a, **k):
                if (s := sink.get()) is not None:
                    s(b.name, size_of(a) + size_of(k))
                return fn(*a, **k)
            return inner
        setattr(b, m, make(fn))
    return b
