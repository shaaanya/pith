# InfoParser

A local-first personal knowledge system. You send it things you want to keep (URLs, notes, files, PDFs,
images, videos, a Telegram export). It stores the original, extracts the text, distils it into small
knowledge items with a recorded provenance, and lets you search and ask questions with cited sources.

It does not require a model or an account. With no model configured, a deterministic extractive fallback
(`heuristic`) does the distillation and `ask` returns cited excerpts instead of a generated answer. Models
(local servers, a command-line tool, or a hosted API) are optional backends behind one interface.

Status: Python 3.13, standard library plus `numpy`. The test suite and a clean-home demo are recorded in
[docs/verification.md](docs/verification.md). Several things are NOT verified; read
[docs/limitations.md](docs/limitations.md) before relying on it.

## Install and first run

    uv sync
    uv run infoparser          # creates ~/InfoParser, starts worker + folder watcher + dashboard, opens the browser

That one command is `infoparser run` (Ctrl-C stops it). Choose models in the dashboard's **Settings** tab
(add a local server such as Ollama, click "Detect models", pick one, Save; it applies immediately and is
stored in `~/InfoParser/config.toml`). Hosted backends read their API key from an environment variable of
the launching shell; keys are never typed into the UI. Backends that run a program (`cli`, `tesseract`,
`whisper_cpp`) are edited in the config file only.

The same things from the command line:

    uv run infoparser init                       # creates ~/InfoParser (or $INFOPARSER_HOME)
    uv run infoparser submit "https://example.com/some-article"
    uv run infoparser submit "a note to remember" --context "why I saved it"
    uv run infoparser worker --once              # process everything queued, then exit
    uv run infoparser search "keywords"
    uv run infoparser ask "a question about what you saved"
    uv run infoparser export                     # write the Markdown vault

For a long-running setup use `uv run infoparser run` (worker + dashboard on 127.0.0.1 + drop-folder
watcher). See [docs/deployment.md](docs/deployment.md).

## What it does

- Ingest: one contract, `Inbox.submit()`, used by the CLI, a watched folder, a Telegram Desktop export
  importer, and a token-protected local HTTP endpoint. A submission is durable before it returns; nothing
  is extracted in the submit path. See [docs/inbox-contract.md](docs/inbox-contract.md).
- Process: web pages, PDFs, docx/pptx/xlsx, images (OCR), video/audio (captions first, then
  transcription), plain text. See [docs/pipeline.md](docs/pipeline.md).
- Provenance: every knowledge item is `stated` (backed by a quote that is checked against the source),
  `inferred`, or `external`. A `stated` item whose quote is not found is downgraded.
- Retrieve: SQLite FTS5 plus optional embeddings fused by reciprocal rank fusion; `ask` answers only from
  numbered excerpts and validates the citations.
- Keep: one SQLite file, content-addressed original blobs, and a Markdown vault that is a derived export.
  `backup` / `restore` / `verify` are built in. See [docs/backup-restore.md](docs/backup-restore.md).

## Documentation

| Document | Contents |
|---|---|
| [architecture](docs/architecture.md) | Layers, storage, what is source of truth |
| [inbox-contract](docs/inbox-contract.md) | Submission, states, retry, duplicates, HTTP/folder/Telegram adapters |
| [pipeline](docs/pipeline.md) | Extractors, chunking, distillation, provenance, dedupe |
| [note-pipeline](docs/note-pipeline.md) | Knowledge notes: spec, architecture, diagnosis, benchmark results, limitations |
| [data-model](docs/data-model.md) | Tables (schema v3), ids, locators |
| [providers](docs/providers.md) | Ports, backends, task chains, agentic-CLI assessment, privacy/egress |
| [capabilities](docs/capabilities.md) | Capability flags and how tasks resolve to backends |
| [configuration](docs/configuration.md) | Every config key and environment variable |
| [deployment](docs/deployment.md) | Running it, files on disk, security model |
| [backup-restore](docs/backup-restore.md) | Backup, verify, restore |
| [testing](docs/testing.md) | Unit, e2e and live tests, environment variables |
| [limitations](docs/limitations.md) | Known gaps and everything that is UNVERIFIED |
| [roadmap](docs/roadmap.md) | Not built |
| [verification](docs/verification.md) | Test run, provider matrix, end-to-end demo |
| [recipes](docs/recipes/) | iOS Shortcut, Telegram bot, browser bookmarklet, launchd |

Design rationale: [docs/superpowers/specs/2026-11-05-infoparser-design.md](docs/superpowers/specs/2026-11-05-infoparser-design.md).
Build checklist: [docs/CHECKLIST.md](docs/CHECKLIST.md). Sample config: [config.sample.toml](config.sample.toml).

## Privacy in one paragraph

Hosted backends are blocked unless `[privacy] allow_remote = true`. An `openai_compat` backend with a
non-loopback `base_url` counts as remote even if you forget to say so; `cli` backends are trusted as
declared (their locality cannot be detected). Web pages you submit are fetched
from their own sites, and `yt-dlp` contacts the video sites you submit. `infoparser egress` and
`infoparser doctor` show which routes could send text off the machine. See the privacy section of
[docs/providers.md](docs/providers.md).
