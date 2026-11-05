import argparse
import os
import sys
from pathlib import Path

from infoparser.config import load_config
from infoparser.services import build


def _services(a):
    env = dict(os.environ)
    if a.home:
        env["INFOPARSER_HOME"] = a.home
    return build(load_config(Path(a.config) if a.config else None, env))


def _init(a):
    s = _services(a)
    for d in (s.cfg.blobs_dir, s.cfg.vault_dir, *s.cfg.watch_dirs[:1]):
        Path(d).mkdir(parents=True, exist_ok=True)
    print(f"initialized {s.cfg.home}")


def _submit(a):
    s = _services(a)
    if a.file:
        p = Path(a.file)
        r = s.inbox.submit(adapter="cli", file=p, filename=p.name, user_context=a.context)
    elif a.text:
        r = s.inbox.submit(adapter="cli", text=a.text, user_context=a.context)
    else:
        sys.exit("submit needs TEXT_OR_URL or --file")
    print(f"submitted {r.id}")


def _inbox(a):
    for r in _services(a).inbox.list(a.status):
        what = r["canonical_url"] or r["original_filename"] or (r["payload_text"] or "")[:50].replace("\n", " ")
        print(f"{r['id']}  {r['status']:<19} {r['content_type'] or '-':<8} {what}" + (f"  !{r['error']}" if r["error"] else ""))


def _retry(a):
    _services(a).inbox.retry(a.id)
    print(f"requeued {a.id}")


def _worker(a):
    from infoparser.pipeline import runner
    from infoparser.worker import Worker
    s = _services(a)
    w = Worker(s.conn, s.inbox, s.queue, lambda i: runner.process(s, i))
    if a.once:
        n = 0
        while w.run_once():
            n += 1
        print(f"processed {n} job(s)")
    else:
        try:
            w.run_forever()
        except KeyboardInterrupt:
            pass


def _search(a):
    from infoparser.retrieval.search import search
    for h in search(_services(a), " ".join(a.query), limit=a.limit):
        print(f"{h.item_id}  [{h.kind}/{h.provenance}] {h.title}\n    {h.snippet}" + (f"  ({h.locator})" if h.locator else ""))


def _show(a):
    from infoparser.store.knowledge import get_item
    s = _services(a)
    try:
        r = s.inbox.get(a.id)
    except KeyError:
        k = get_item(s.conn, a.id)
        if not k:
            sys.exit(f"not found: {a.id}")
        print(f"{k['id']} [{k['kind']}/{k['provenance']}] {k['title']}\n{k['body']}\nevidence: {k['data'].get('evidence')}")
        return
    print(f"{r['id']} status={r['status']} type={r['content_type']} attempts={r['attempts']}")
    if r["error"]:
        print(f"error: {r['error']}")
    if r["user_context"]:
        print(f"context: {r['user_context']}")
    for k in s.conn.execute("SELECT id FROM knowledge_items WHERE source_id=? AND deleted_at IS NULL", (r["source_id"],)):
        i = get_item(s.conn, k["id"])
        print(f"- {i['id']} [{i['kind']}/{i['provenance']}] {i['title']}: {i['body']}")
    for e in s.conn.execute("SELECT stage, status, detail FROM processing_events WHERE inbox_id=? ORDER BY id", (a.id,)):
        print(f"  event {e['stage']} {e['status']} {e['detail'] or ''}")


def _doctor(a):
    s = _services(a)
    print(f"home: {s.cfg.home}\ndb: {s.cfg.db_path}\nallow_remote: {s.cfg.allow_remote}")
    for d in s.registry.describe():
        print(f"backend: {d}")
    for k in s.registry.skipped:
        print(f"skipped: {k}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="infoparser")
    p.add_argument("--home")
    p.add_argument("--config")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init").set_defaults(f=_init)
    c = sub.add_parser("submit")
    c.add_argument("text", nargs="?")
    c.add_argument("--context")
    c.add_argument("--file")
    c.set_defaults(f=_submit)
    c = sub.add_parser("inbox")
    c.add_argument("--status")
    c.set_defaults(f=_inbox)
    c = sub.add_parser("retry")
    c.add_argument("id")
    c.set_defaults(f=_retry)
    c = sub.add_parser("worker")
    c.add_argument("--once", action="store_true")
    c.set_defaults(f=_worker)
    c = sub.add_parser("search")
    c.add_argument("query", nargs="+")
    c.add_argument("--limit", type=int, default=10)
    c.set_defaults(f=_search)
    c = sub.add_parser("show")
    c.add_argument("id")
    c.set_defaults(f=_show)
    sub.add_parser("doctor").set_defaults(f=_doctor)
    a = p.parse_args(argv)
    a.f(a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
