"""pith command line.

--home / --config are accepted before AND after the subcommand; the subcommand position wins,
then PITH_HOME / PITH_CONFIG, then the defaults.
"""
# pylint: disable=import-outside-toplevel  # lazy imports keep CLI start-up fast
import argparse
import functools
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import cast

from pith.config import ConfigError, load_config
from pith.domain.display import inbox_label
from pith.services import build


def resolved(args, name):
    """Value of --home/--config: subcommand position wins over the top-level position."""
    return getattr(args, name + "_sub", None) or getattr(args, name + "_top", None)


def _cfg(a):
    env = dict(os.environ)
    if home := resolved(a, "home"):
        env["PITH_HOME"] = home
    config = resolved(a, "config")
    return load_config(Path(config) if config else None, env)


def _services(a):
    return build(_cfg(a))


def _in_use(fn):
    """Hold the shared in-use lock while a long-running command runs (restore refuses meanwhile)."""
    @functools.wraps(fn)
    def guarded(a):
        from pith import locks
        try:
            with locks.in_use(_cfg(a).home):
                fn(a)
        except locks.InUseError as e:
            sys.exit(f"error: {e}")
    return guarded


def _make_dirs(cfg):
    """Create the home layout (idempotent); `init` and `run` both use it."""
    for d in (cfg.home, cfg.blobs_dir, cfg.vault_dir, *cfg.watch_dirs[:1]):
        Path(d).mkdir(parents=True, exist_ok=True)
    Path(cfg.home).chmod(0o700)


def _init(a):
    s = _services(a)
    _make_dirs(s.cfg)
    print(f"initialized {s.cfg.home}")
    if sys.stdin.isatty() and sys.stdout.isatty():  # offer the channel setup; never in scripts
        print()
        _setup(a)


def _setup(a):
    from pith.adapters.setup import run_setup
    s = _services(a)
    _make_dirs(s.cfg)
    rc = run_setup(s)
    if rc:
        sys.exit(rc)


@_in_use
def _submit(a):
    s = _services(a)
    if a.file:
        p = Path(a.file)
        try:
            r = s.inbox.submit(adapter="cli", file=p, filename=p.name, user_context=a.context)
        except OSError as e:  # missing path, a directory, no permission
            sys.exit(f"error: cannot read {p}: {e.strerror or e}")
    elif a.text:
        r = s.inbox.submit(adapter="cli", text=a.text, user_context=a.context)
    else:
        sys.exit("error: submit needs TEXT_OR_URL or --file")
    print(f"submitted {r.id}")


@_in_use
def _reprocess(a):
    """Re-run the pipeline for saved items (new model, new prompts, a new focus).

    Non-destructive: items you edited are kept, replaced ones are snapshotted in
    knowledge_versions, and the original sources and blobs are never touched."""
    s = _services(a)
    ids = a.ids or [r["id"] for r in s.conn.execute(
        "SELECT id FROM inbox_items WHERE status='processed' AND source_id IS NOT NULL"
        " AND duplicate_of IS NULL ORDER BY submitted_at")]
    for i in ids:
        if a.why:
            s.inbox.add_context(i, a.why)
        s.inbox.retry(i)
    print(f"requeued {len(ids)} item(s); run `pith worker` to process them")


def _inbox(a):
    for r in _services(a).inbox.list(a.status):
        what = inbox_label(r, 50)
        err = f"  !{r['error']}" if r["error"] else ""
        print(f"{r['id']}  {r['status']:<19} {r['content_type'] or '-':<8} {what}{err}")


@_in_use
def _retry(a):
    try:
        _services(a).inbox.retry(a.id)
    except KeyError:
        sys.exit(f"error: unknown id {a.id}")
    print(f"requeued {a.id}")


@_in_use
def _worker(a):
    from pith import locks
    from pith.pipeline import runner
    from pith.worker import Worker
    s = _services(a)
    w = Worker(s.conn, s.inbox, s.queue, lambda i: runner.process(s, i),
               worker_id=locks.new_worker_id())
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


@_in_use
def _clarify(a):
    """Attach the user clarification to an item and re-queue it (CLI twin of the dashboard)."""
    text = " ".join(a.text).strip()
    if not text:
        sys.exit("error: clarification text is empty")
    try:
        _services(a).inbox.clarify(a.id, text)
    except KeyError:
        sys.exit(f"error: unknown id {a.id}")
    print(f"requeued {a.id} with your clarification")


def _cite_line(n, title, url, locator):
    return f"[{n}] {title} \u2014 {url or '-'} \u2014 {locator or '-'}"


def _search(a):
    from pith.retrieval.search import search_ex
    r = search_ex(_services(a), " ".join(a.query), limit=a.limit, mode=a.mode)
    for w in r.warnings:
        print(f"warning: {w}", file=sys.stderr)
    for n, h in enumerate(r.hits, 1):
        cite = _cite_line(n, h.title, h.source_url, h.locator)
        print(f"{cite}\n    {h.item_id or 'segment'} [{h.kind}/{h.provenance}] {h.snippet}")
    if r.egress:
        print(f"egress: text sent to remote backend(s): {', '.join(r.egress)}", file=sys.stderr)


def _ask(a):
    from pith.retrieval.ask import ask
    ans = ask(_services(a), " ".join(a.question), limit=a.k, retrieval_only=a.retrieval_only)
    if a.json:
        print(json.dumps(ans.to_dict(), indent=2))
        return
    print(f"mode: {ans.mode} (retrieval: {ans.retrieval_mode})")
    if ans.interpretation:
        print(f"\n{ans.interpretation}\n(generated by {ans.generated_by}; "
              "interpretation, not source text)")
    if ans.message:
        print(ans.message)
    for e in ans.retrieved:
        print(_cite_line(e.n, e.title, e.deep_link or e.url, e.locator))
    for w in ans.warnings:
        print(f"warning: {w}", file=sys.stderr)
    if ans.egress:
        print(f"egress: text sent to remote backend(s): {', '.join(ans.egress)}", file=sys.stderr)


def _host(fn, a):
    from pith import host
    try:
        return fn(host, _services(a), a)
    except host.HostError as e:
        sys.exit(f"error: {e}")


def _host_prompt(a):
    print(json.dumps(_host(lambda h, s, a: h.prompt(s, a.id, ack=a.ack_host), a), indent=2))


def _host_apply(a):
    reply = sys.stdin.read() if a.file in (None, "-") else Path(a.file).read_text(encoding="utf-8")
    n = _host(lambda h, s, a: h.apply(s, a.id, a.sha, reply, a.agent), a)
    print(f"saved {n} items")


def _show(a):
    from pith.store.knowledge import get_item
    s = _services(a)
    try:
        r = s.inbox.get(a.id)
    except KeyError:
        k = get_item(s.conn, a.id)
        if not k:
            sys.exit(f"error: unknown id {a.id}")
        print(f"{k['id']} [{k['kind']}/{k['provenance']}] {k['title']}\n{k['body']}\n"
              f"evidence: {k['data'].get('evidence')}")
        return
    print(f"{r['id']} status={r['status']} type={r['content_type']} attempts={r['attempts']}")
    if r["error"]:
        print(f"error: {r['error']}")
    if r["user_context"]:
        print(f"context: {r['user_context']}")
    conn = cast(sqlite3.Connection, vars(s)["conn"])  # Services.conn is annotated `object`
    for k in conn.execute("SELECT id FROM knowledge_items WHERE source_id=? AND deleted_at IS NULL",
                          (r["source_id"],)):
        i = get_item(s.conn, k["id"])
        print(f"- {i['id']} [{i['kind']}/{i['provenance']}] {i['title']}: {i['body']}")
    for e in conn.execute("SELECT stage, status, detail FROM processing_events WHERE inbox_id=?"
                          " ORDER BY id", (a.id,)):
        print(f"  event {e['stage']} {e['status']} {e['detail'] or ''}")


@_in_use
def _reindex(a):
    from pith.providers import egress
    from pith.retrieval.index import reindex
    s = _services(a)
    with egress.collect() as sent:
        n = reindex(s, prune_old=a.prune_old)
    for name, size in sent.items():
        print(f"egress: {size} bytes of text sent to remote backend {name}", file=sys.stderr)
    print(f"reindexed {n} vectors" if n
          else "nothing to reindex (no embedding backend configured?)")


def _doctor(a):
    from pith import doctor
    from pith.providers import locality
    cfg = _cfg(a)
    checks = doctor.run(cfg, full=a.full)  # config only: never builds Services (no db created)
    checks += [doctor.Check("locality", "WARN", w) for w in locality.warnings(cfg.backends)]
    print(doctor.to_json(checks) if a.json else doctor.render(checks))
    sys.exit(doctor.exit_code(checks))


def _egress(a):
    from pith import doctor
    r = doctor.egress_report(_cfg(a))
    print(json.dumps(r, indent=2) if a.json else doctor.render_egress(r))
    if not a.json:
        print("cli backends are trusted as declared: their locality cannot be detected.")


@_in_use
def _export(a):
    from pith.export import export_vault
    s = _services(a)
    print(f"exported {export_vault(s, keep=a.keep)} item(s) to {s.cfg.vault_dir}")


def _backup(a):
    from pith import backup
    cfg = _cfg(a)
    try:
        dest = Path(a.dest) if a.dest else cfg.home / "backups"
        print(f"backup written: {backup.backup(cfg, dest)}")
    except (backup.RestoreError, OSError) as e:
        sys.exit(f"error: {e}")


def _restore(a):
    from pith import backup, locks
    cfg = _cfg(a)
    try:
        backup.restore(Path(a.archive), cfg.home, force=a.force)
    except (backup.RestoreError, locks.InUseError, OSError) as e:
        sys.exit(f"error: {e}")
    print(f"restored {a.archive} into {cfg.home}")


def _verify(a):
    from pith import backup
    try:
        m = backup.verify(Path(a.archive))
    except (backup.RestoreError, OSError) as e:
        sys.exit(f"error: {e}")
    print(f"ok: schema v{m['schema_version']}, {m['blob_count']} blob(s), "
          f"created {m['created_at']}, {m['counts']}")


@_in_use
def _digest(a):
    from pith import digest
    try:
        r = digest.run(_services(a), since=a.since, dry_run=a.dry_run, force=a.force)
    except ValueError as e:
        sys.exit(f"error: {e}")
    print(r.text)
    if r.path and not r.skipped:
        print(f"written: {r.path}", file=sys.stderr)


from pith.adapters import CHANNELS  # noqa: E402  # light: the registry only imports lazily

ADAPTERS = (*CHANNELS, "telegram_export", "http")


def _adapters_list(_args):
    for n in ADAPTERS:
        print(n)


@_in_use
def _watch(a):
    from pith.adapters.fs import FsAdapter
    s = _services(a)
    fa = FsAdapter(s.inbox, s.cfg.watch_dirs)
    if a.once:
        fa.poll()  # first sighting only records sizes; use two polls for a one-shot scan
        print(f"submitted {fa.poll()} file(s) "
              "(files modified in the last 2s are skipped by the mtime guard)")
        return
    try:
        fa.run_forever()
    except KeyboardInterrupt:
        pass


@_in_use
def _run_channel(a):
    import threading
    from pith.adapters import build_channel
    from pith.adapters.base import ChannelState, run_channel
    s = _services(a)
    try:
        ch = build_channel(a.name, s)
    except (ValueError, OSError) as e:
        sys.exit(f"error: {e}")
    try:
        run_channel(ch, ChannelState(s.conn, a.name), threading.Event())
    except KeyboardInterrupt:
        pass


def _adapters_pair(a):
    from pith.adapters.base import ChannelState
    from pith.adapters.telegram_bot import new_pairing_code
    s = _services(a)
    code = new_pairing_code(ChannelState(s.conn, a.name))
    print(f"pairing code: {code}\n"
          "1. Create a bot with @BotFather and save its token in "
          f"{s.cfg.home}/telegram_token (or set PITH_TELEGRAM_TOKEN).\n"
          "2. Add this to your config.toml:\n[channels.telegram]\nenabled = true\n"
          "3. Run `pith run`, open a private chat with your bot, press Start and send it the code "
          "above when it asks. The bot confirms and that chat is allowed.")


def _adapters_run(a):
    if a.name == "fs":
        return _watch(a)
    if a.name == "http":
        return _serve_http(a)
    if a.name in CHANNELS:
        return _run_channel(a)
    sys.exit(f"error: adapter {a.name} is not a long-running adapter (use import-telegram)")


@_in_use
def _import_telegram(a):
    from pith.adapters.telegram_export import import_export
    try:
        r = import_export(_services(a).inbox, Path(a.path), since=a.since,
                          fetch_urls=a.fetch_urls)
    except (ValueError, OSError) as e:
        sys.exit(f"error: {e}")
    print(f"submitted {r.submitted}, duplicates {r.duplicates}, skipped {r.skipped}")


@_in_use
def _serve_http(a):
    from pith.adapters.http_ingest import IngestServer
    s = _services(a)
    try:
        srv = IngestServer(s.cfg)
    except ValueError as e:
        sys.exit(f"error: {e}")
    host, port = srv.server_address[:2]
    print(f"listening on http://{host}:{port} (token in {s.cfg.home}/http_token)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


def _run(a):
    import signal
    import threading
    from pith import run_all
    import webbrowser
    cfg = _cfg(a)
    _make_dirs(cfg)
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    # a terminal launch opens the browser; launchd/cron (no TTY) does not
    opening = sys.stdout.isatty() if a.open is None else a.open

    def ready(info):
        if info["url"]:
            print(f"dashboard: {info['url']}\n(Ctrl-C to stop)", flush=True)
            if opening:
                webbrowser.open(info["url"])
        else:
            print("running (no dashboard); Ctrl-C to stop", flush=True)
    try:
        run_all.run(cfg, a.port, dashboard=not a.no_dashboard, watch=not a.no_watch,
                    stop=stop, on_ready=ready)
    except KeyboardInterrupt:
        stop.set()
    except run_all.RunError as e:
        sys.exit(f"error: {e}")


@_in_use
def _dashboard(a):
    from pith.dashboard.server import make_server
    s = _services(a)
    try:
        srv = make_server(s, port=a.port)
    except OSError as e:
        sys.exit(f"error: port {a.port} in use or unavailable: {e}")
    print(f"dashboard: http://127.0.0.1:{srv.server_address[1]}/?token={srv.token}\n"
          "(no worker: use `pith run` to process)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


def _arg(*flags, **kw):
    return flags, kw


_PORT = _arg("--port", type=int, default=8777)
_ONCE = _arg("--once", action="store_true")
_JSON = _arg("--json", action="store_true")
# subcommand -> (handler, arguments)
COMMANDS = {
    "init": (_init, []),
    "setup": (_setup, []),
    "submit": (_submit, [_arg("text", nargs="?"), _arg("--context", "--why"), _arg("--file")]),
    "inbox": (_inbox, [_arg("--status")]),
    "retry": (_retry, [_arg("id")]),
    "reprocess": (_reprocess, [_arg("ids", nargs="*", help="inbox ids (default: every processed item)"),
                               _arg("--why", help="a reason/focus to add before re-running")]),
    "clarify": (_clarify, [_arg("id"), _arg("text", nargs="+")]),
    "worker": (_worker, [_ONCE]),
    "search": (_search, [_arg("query", nargs="+"), _arg("--limit", type=int, default=10),
                         _arg("--mode", choices=["fts", "hybrid"], default="hybrid")]),
    "ask": (_ask, [_arg("question", nargs="+"), _JSON, _arg("--k", type=int, default=8),
                   _arg("--retrieval-only", action="store_true",
                        help="numbered excerpts only; call no answer backend (host-agent mode)")]),
    "host-prompt": (_host_prompt, [_arg("id", help="source id"),
                                   _arg("--ack-host", action="store_true",
                                        help="the host agent's model may see this text")]),
    "host-apply": (_host_apply, [_arg("id", help="source id"), _arg("file", nargs="?"),
                                 _arg("--sha", required=True), _arg("--agent", default="agent")]),
    "show": (_show, [_arg("id")]),
    "reindex": (_reindex, [_arg("--prune-old", action="store_true")]),
    "doctor": (_doctor, [_JSON, _arg("--full", action="store_true",
                                     help="verify every blob, not a sample")]),
    "egress": (_egress, [_JSON]),
    "export": (_export, [_arg("--keep", action="store_true",
                              help="keep vault files of deleted/renamed items")]),
    "backup": (_backup, [_arg("dest", nargs="?")]),
    "restore": (_restore, [_arg("archive"), _arg("--force", action="store_true")]),
    "verify": (_verify, [_arg("archive")]),
    "digest": (_digest, [_arg("--since", help="YYYY-MM-DD or a number of days"),
                         _arg("--dry-run", action="store_true"),
                         _arg("--force", action="store_true",
                              help="write even inside the interval / overwrite today's digest")]),
    "watch": (_watch, [_ONCE]),
    "import-telegram": (_import_telegram, [
        _arg("path"), _arg("--since"),
        _arg("--fetch-urls", action="store_true",
             help="fetch URL-only messages (public addresses only; default: keep them as notes, "
                  "never fetched)")]),
    "serve-http": (_serve_http, []),
    "run": (_run, [_PORT, _arg("--no-dashboard", action="store_true"),
                   _arg("--no-watch", action="store_true"),
                   _arg("--open", action=argparse.BooleanOptionalAction, default=None,
                        help="open the browser (default: only when run in a terminal)")]),
    "dashboard": (_dashboard, [_PORT]),
}


def _location_flags(parser, suffix):
    """--home/--config with their own dest per position, so neither can clobber the other."""
    for name in ("home", "config"):
        parser.add_argument(f"--{name}", dest=f"{name}_{suffix}", default=argparse.SUPPRESS)


def build_parser():
    """The full argument parser (separate from main() so tests can inspect it)."""
    common = argparse.ArgumentParser(add_help=False)
    _location_flags(common, "sub")
    parser = argparse.ArgumentParser(prog="pith")
    _location_flags(parser, "top")
    sub = parser.add_subparsers(dest="cmd")  # no subcommand: main() runs `run`
    for name, (handler, arguments) in COMMANDS.items():
        cmd = sub.add_parser(name, parents=[common])
        for flags, kw in arguments:
            cmd.add_argument(*flags, **kw)
        cmd.set_defaults(f=handler)
    adapters = sub.add_parser("adapters", parents=[common])
    asub = adapters.add_subparsers(dest="acmd", required=True)
    asub.add_parser("list", parents=[common]).set_defaults(f=_adapters_list)
    run = asub.add_parser("run", parents=[common])
    run.add_argument("name", choices=ADAPTERS)
    run.add_argument(*_ONCE[0], **_ONCE[1])
    run.set_defaults(f=_adapters_run)
    pair = asub.add_parser("pair", parents=[common])
    pair.add_argument("name", choices=["telegram"])
    pair.set_defaults(f=_adapters_pair)
    return parser


def main(argv=None):
    """Entry point."""
    argv = sys.argv[1:] if argv is None else list(argv)
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.cmd is None:  # bare `pith` (maybe with --home/--config): launch everything
        args = parser.parse_args([*argv, "run"])
    try:
        args.f(args)
    except ConfigError as e:
        sys.exit(f"error: {e}")


if __name__ == "__main__":
    sys.exit(main())
