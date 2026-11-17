# Architecture

Pith is one Python process (or a few short ones) over one SQLite database. The structure is
hexagonal: a domain/pipeline core talks to the outside world only through ports, and adapters and backends
plug in at the edges.

```
adapters: CLI | channels (drop folder, Telegram bot) | Telegram export | HTTP /v1/inbox | dashboard "add"
        |   Inbox.submit()                       <- the only ingress contract
        v
inbox (domain) --> jobs table (SQLite leases) --> worker
                                |
                     pipeline/runner.py
   detect -> extract -> chunk -> distill -> save -> entities/topics -> embed -> dedupe/relate
                                |   ports only
   providers/ports.py   TextGenerator  Embedder  Reranker  Transcriber  VisionDescriber  OCR
                                |
   backends: openai_compat | cli | anthropic | whisper_cpp | tesseract | heuristic
        v
store: SQLite (+FTS5, embeddings) | blobs/ (content-addressed originals) | vault/ (derived Markdown)
        v
retrieval (search, ask) | dashboard (thin HTTP + one static page) | CLI
```

## Layers and the rules that are tested

| Package | Role |
|---|---|
| `domain/` | Status and provenance enums, `SubmitResult`, URL canonicalisation, text normalisation. No I/O. |
| `inbox/` | `Inbox` service: submit, dedupe, requeue, events. `ingest.py` holds the submit-body validation shared by the HTTP adapter and the dashboard. |
| `jobs.py`, `worker.py` | Job queue with leases, heartbeats, backoff; worker loop. |
| `pipeline/` | Runner, chunking, distillation, provenance check, entities, dedupe, extractors. |
| `providers/` | `ports.py` (the only provider surface the core imports), `registry.py`, one module per backend, `egress.py`. |
| `retrieval/` | FTS and vector search, RRF fusion, `ask`. |
| `store/` | Connection and migrations (`db.py`), blob store, knowledge store, vectors. |
| `adapters/` | Channels (`base.py` protocol and run loop; `fs`, `telegram_bot`), plus `telegram_export` and `http_ingest`. A channel is `name`, `interval`, `poll()`; register it in `adapters/__init__.py` `CHANNELS`. They only call `Inbox.submit()`; they never reply to content (Telegram's pairing handshake aside). |
| `dashboard/` | `api.py` (logic over services), `server.py` (routing and auth), `static/index.html` (renders only). |
| `export.py`, `backup.py`, `digest.py`, `doctor.py`, `run_all.py`, `cli.py` | Operations. |

`tests/test_layering.py` scans `domain`, `pipeline`, `inbox` and `retrieval` with the AST and fails if any
of them imports a concrete backend module (`heuristic`, `openai_compat`, `cli_backend`, `anthropic`,
`tesseract`, `whisper_cpp`). Only `providers/registry.py` imports backends, lazily, by the name in the
config.

## Storage

- One SQLite file, `<home>/infoparser.db`: WAL journal, `busy_timeout=5000`, foreign keys on. Schema version
  is `PRAGMA user_version` (currently 3), upgraded by numbered `.sql` migrations; the migration takes
  `BEGIN IMMEDIATE` first and re-reads the version inside the lock, so two starters on a fresh database do
  not race. Job claims also run inside `BEGIN IMMEDIATE`.
- Originals are stored as content-addressed blobs under `<home>/blobs/<ab>/<cd>/<sha256>`. A submitted
  file or an uploaded body is hashed and written before the database row; blob names are validated as
  64 hex characters before any path is built.
- Search indexes (FTS5 tables) and embeddings live in the same database and can be rebuilt from the
  segments and items. `pith reindex` rebuilds embeddings for the active embedding model.
- The Markdown vault (`<home>/vault/<yyyy>/<slug>-<id>.md`) is a derived export written by
  `pith export`. It is regenerated from the database and is never read back. Edit items through the
  dashboard, not the vault files.

What is the source of truth: the database plus the blobs. Everything else (vault, FTS indexes,
embeddings, digests) can be regenerated or is a report.

## Concurrency and recovery

- `Inbox.submit()` writes the blob, the inbox row and a pending job in one transaction and runs no
  extraction. A crash after the blob write leaves at most an unreferenced blob.
- A worker claims a job with a lease (`lease_seconds`, default 300) and a heartbeat thread keeps it alive.
  If the worker dies, the lease expires and the job is reclaimed; a stale worker's late completion is
  discarded, and its late WRITES are too: the worker publishes (job, worker id, attempt) in a context
  variable, and the source/segment/item save and the twin-sharing step verify inside their own
  transaction that the jobs row is still running under that worker and attempt (a stale worker raises
  "lost the lease" and writes nothing). Heartbeats only extend a lease still owned by the sender.
  Direct library calls outside a Worker are not fenced. Failures retry with exponential backoff (5 s base, 1 h cap) up to `max_attempts` (default 5),
  then the item is `failed` and the original is untouched.
- `pith run` holds an `flock` on `<home>/run.lock` so only one `run` exists per home. The
  standalone `worker`, `dashboard`, `watch` and `serve-http` commands hold a shared `flock` on
  `<home>/in-use.lock` (they can run side by side and next to `run`); `restore` takes it exclusively and
  also refuses while a job lease is live. Standalone workers get ids like `host-pid-random`, so the
  stale-completion fence works across processes (`run` uses the fixed id `run`).

## Model independence

The pipeline never names a model. `Registry` resolves a task (`distill`, `embed`, ...) to an ordered chain
of configured backends; the extractive `heuristic` backend is always the last text backend, so processing
completes with no model at all. See providers.md and [capabilities.md](capabilities.md).
The decision about command-line agents is in providers.md.

## Dashboard and ingest servers

Both are stdlib `ThreadingHTTPServer`s bound to 127.0.0.1, with a bearer token, a Host-header allow-list
(DNS rebinding), no CORS headers, and a strict content security policy for the dashboard. They share one
token file, `<home>/http_token`. `pith run` starts the worker, the dashboard and the folder watcher;
the HTTP ingest endpoint is a separate command (`pith serve-http`). See deployment.md.
