# Configuration

Configuration is one optional TOML file. There is no automatic search for it: pass `--config PATH` (before
or after the subcommand) or set `INFOPARSER_CONFIG=PATH`. Without a file every default below applies, which
means: home `~/InfoParser`, no model backends (the `heuristic` fallback only), nothing remote. Start from
[config.sample.toml](../config.sample.toml); it loads as-is, and its model names are placeholders
(`REPLACE_WITH_...`) that you must replace. `tests/test_config_sample.py` checks that the sample loads and builds a registry.

Order of precedence for the home directory: `--home` flag, then `INFOPARSER_HOME`, then `home` in the file,
then `~/InfoParser`. (The flag works by overriding the environment value for that command.) A relative `home`
is resolved against your user home.

## Top level

| Key | Default | Meaning |
|---|---|---|
| `home` | `~/InfoParser` | Data directory: `infoparser.db`, `blobs/`, `vault/`, `inbox/`, `backups/`, `digests/`, `http_token`, `run.lock` |

## `[privacy]`

| Key | Default | Meaning |
|---|---|---|
| `allow_remote` | `false` | Remote-tagged backends are removed from every task chain until this is `true` |

## `[limits]`

| Key | Default | Meaning |
|---|---|---|
| `max_attempts` | `5` | Processing attempts before an item is `failed` |
| `lease_seconds` | `300` | Job lease; the heartbeat renews it every third of this |
| `max_fetch_bytes` | `50000000` | Cap for fetched pages, uploaded/dropped files and HTTP ingest bodies |

## `[watch]`

| Key | Default | Meaning |
|---|---|---|
| `dirs` | `["<home>/inbox"]` | Folders polled by the drop-folder adapter (`watch`, `run`). `~` is expanded. Setting it replaces the default. `init` creates only the first one |

## `[http]`

Used by `infoparser serve-http` (and its token by the dashboard).

| Key | Default | Meaning |
|---|---|---|
| `bind` | `127.0.0.1` | Listen address. A non-loopback value requires `token` |
| `port` | `8787` | Listen port |
| `token` | generated | Bearer token. If unset, one is generated into `<home>/http_token` (0600). Also `INFOPARSER_HTTP_TOKEN` |

The dashboard port is not a config key: `infoparser run --port N` / `infoparser dashboard --port N`
(default 8777).

## `[digest]`

| Key | Default | Meaning |
|---|---|---|
| `interval_days` | `7` | At most one digest per interval unless `digest --force` |
| `max_items` | `20` | Cap on items listed per digest section |

## `[media]`

| Key | Default | Meaning |
|---|---|---|
| `yt_dlp` | `yt-dlp` | Executable for video metadata and captions. Also `INFOPARSER_YT_DLP` |
| `ffmpeg` | `ffmpeg` | Executable for audio conversion and frames. Also `INFOPARSER_FFMPEG` |

## `[backends.NAME]`

`NAME` is yours. `type` selects the implementation; the other keys depend on it. Unknown types, missing
required keys and unknown task references fail at load with a message naming the backend.

Common: `type`, `locality` (`local` or `remote`; anything else is a config error), `timeout` (seconds).
When `locality` is absent: an `openai_compat` backend is `local` only if its `base_url` host is loopback
(`localhost`, `127.0.0.0/8`, `::1`) and `remote` for every other host; a `cli` backend is `local`
(a command cannot be inspected). An explicit `locality = "local"` on a non-loopback `openai_compat` host
is honoured (a LAN server you trust), and `infoparser doctor` warns about it.

| `type` | Keys |
|---|---|
| `heuristic` | none |
| `openai_compat` | `base_url`*, `model`*, `api_key_env`, `embed_model`, `capabilities` (list from `json_mode`, `vision`, `rerank`, `transcribe`, `embeddings`, `ocr`; `text` is always on), `transcribe_model`, `context_window`, `locality`, `timeout` (120) |
| `cli` | `command`* (list of strings), `prompt_via` (`stdin` default, or `arg`: prompt appended as the last argument), `capabilities` (default `["text"]`), `context_window`, `locality`, `timeout` (300) |
| `anthropic` | `model`*, `api_key_env`*, `base_url`, `anthropic_version`, `max_tokens` (4096), `context_window`, `timeout` (120); always remote |
| `tesseract` | `binary` (`tesseract`), `lang` (`eng`), `timeout` (120) |
| `whisper_cpp` | `binary`*, `model_path`*, `language`, `threads`, `timeout` (3600) |

`*` required. `api_key_env` is the NAME of an environment variable, never the key.

## `[tasks]`

`task = "backend"` or `task = ["backend", "other:model"]`. Task names: `distill`, `classify`, `embed`,
`rerank`, `transcribe`, `describe`, `ocr`, `answer`. See [capabilities.md](capabilities.md).

## Environment variables

| Variable | Effect |
|---|---|
| `INFOPARSER_HOME` | Home directory (see precedence above) |
| `INFOPARSER_CONFIG` | Config file path, used when `--config` is not given |
| `INFOPARSER_HTTP_TOKEN` | Overrides `[http] token` |
| `INFOPARSER_YT_DLP`, `INFOPARSER_FFMPEG` | Override `[media]` executables |
| the variable named by a backend's `api_key_env` | API key for that backend |
| `INFOPARSER_LIVE_CHAT_MODEL`, `INFOPARSER_LIVE_EMBED_MODEL`, `OLLAMA_HOST` | Tests only, see [testing.md](testing.md) |

## Command-line flags that are not in the file

`--home` and `--config` (global); `search --mode {fts,hybrid} --limit N`; `ask --k N --json`;
`doctor --full --json`; `egress --json`; `digest --since --dry-run --force`; `export --keep`;
`reindex --prune-old`; `run --port --no-dashboard --no-watch`. Use `infoparser <command> --help`.
