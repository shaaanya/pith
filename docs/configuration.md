# Configuration

Configuration is one optional TOML file. Order: `--config PATH` (before or after the subcommand), then
`PITH_CONFIG=PATH`, then `<home>/config.toml` if it exists (a `home` key inside that file is ignored).
The dashboard's Settings tab edits `[backends]`, `[tasks]` and `[privacy] allow_remote` in whichever file was
loaded (creating `<home>/config.toml` if none), keeps all other keys, drops comments, keeps a `.bak`, and
applies the change to the running process. It only adds/changes `openai_compat`, `anthropic` and `heuristic`
backends; program-running types stay file-only. "Detect models" queries `<base_url>/models` on localhost only.
A save is validated before the file is replaced. UNVERIFIED: detection against a real Ollama/LM Studio. Without a file every default below applies, which
means: home `~/Pith`, no model backends (the `heuristic` fallback only), nothing remote. Start from
[config.sample.toml](../config.sample.toml); it loads as-is, and its model names are placeholders
(`REPLACE_WITH_...`) that you must replace. `tests/test_config_sample.py` checks that the sample loads and builds a registry.

Order of precedence for the home directory: `--home` flag, then `PITH_HOME`, then `home` in the file,
then `~/Pith`. (The flag works by overriding the environment value for that command.) A relative `home`
is resolved against your user home.

## Top level

| Key | Default | Meaning |
|---|---|---|
| `home` | `~/Pith` | Data directory: `infoparser.db`, `blobs/`, `vault/`, `inbox/`, `backups/`, `digests/`, `http_token`, `run.lock` |

## `[privacy]`

| Key | Default | Meaning |
|---|---|---|
| `allow_remote` | `false` | Remote-tagged backends are removed from every task chain until this is `true`. Must be a real TOML boolean: `"false"` (a string) is a configuration error, not `true` |

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

## `[channels.<name>]`

Channels are one-way feeders into the inbox (see `docs/inbox-contract.md`); `pith run` starts one thread per
enabled channel and `pith adapters run <name>` runs one alone. `fs` is on unless `enabled = false`; every other
channel needs `enabled = true`. Channels only receive; the one exception is the Telegram pairing handshake (below). Status (`last_ok_at`, `last_error`,
`submitted`) and cursors live in the `channel_state` table.

| Key | Default | Meaning |
|---|---|---|
| `fs.enabled` | `true` | The drop-folder channel (folders from `[watch] dirs`) |
| `fs.interval` | `5.0` | Seconds between folder scans |
| `telegram.enabled` | `false` | The Telegram bot channel |
| `telegram.allowed_chat_ids` | `[]` | Chat ids always accepted. Other chats join by pairing (below) |
| `telegram.poll_timeout` | `25` | Long-poll seconds for `getUpdates` |
| `telegram.api_base` | `https://api.telegram.org` | Only change for testing |

Quickest setup: create a bot with @BotFather (you own it), then run `pith setup` (also offered at the end of
`pith init` in a terminal). It asks for the token (hidden), checks it with Telegram, saves it, enables the channel and
prints a one-time pairing code to send to the bot; then `pith run`. Manual setup, which `pith setup` automates:
put the token in `<home>/telegram_token` (mode 0600) or set
`PITH_TELEGRAM_TOKEN`; the token is never read from `config.toml`. Run `pith adapters pair telegram` to get a
one-time code, then send that code to the bot once from the chat you want to use. The bot asks for the code after you press Start, confirms, and then stays silent about content (it never
replies to links, notes or files); the
chat is allowed from then on. Messages from any other chat are ignored. Links, notes, documents, photos, voice,
audio and video you send become inbox items (files up to `max_fetch_bytes`).

## `[http]`

Used by `pith serve-http` (and its token by the dashboard).

| Key | Default | Meaning |
|---|---|---|
| `bind` | `127.0.0.1` | Listen address. A non-loopback value requires `token` |
| `port` | `8787` | Listen port |
| `token` | generated | Bearer token. If unset, one is generated into `<home>/http_token` (0600). Also `PITH_HTTP_TOKEN` |

The dashboard port is not a config key: `pith run --port N` / `pith dashboard --port N`
(default 8777).

## `[digest]`

| Key | Default | Meaning |
|---|---|---|
| `interval_days` | `7` | At most one digest per interval unless `digest --force` |
| `max_items` | `20` | Cap on items listed per digest section |

## `[media]`

| Key | Default | Meaning |
|---|---|---|
| `yt_dlp` | `yt-dlp` | Executable for video metadata and captions. Also `PITH_YT_DLP` |
| `ffmpeg` | `ffmpeg` | Executable for audio conversion and frames. Also `PITH_FFMPEG` |
| `cookies_from_browser` | unset (off) | Opt-in. A `yt-dlp` `BROWSER[:PROFILE]` value such as `firefox:pith`; `yt-dlp` then reads that browser profile's cookies for the hosts in `cookie_domains`. See below |
| `cookie_domains` | `["instagram.com", "tiktok.com"]` | The only hosts (and their subdomains) the cookies are used for |
| `cookie_gap_seconds` | `20` | Minimum seconds between logged-in fetches to one host, so the account is not hit in bursts |

### Instagram and TikTok (login-walled links)

Without a login, Instagram and TikTok refuse `yt-dlp`, so a shared reel stops at `needs_clarification` ("login or
rate limit ... paste the transcript or text"). The only way a bare link works is to fetch it as a logged-in user:

1. **Use a throwaway account, never your main one.** Automated fetching is against Instagram's terms and can get
   an account flagged or locked. Pith never touches the account's password; it only reads cookies.
2. Create a dedicated browser profile (Firefox: `firefox -P` -> create profile `pith`), open it, and log in to the
   throwaway account there. Firefox is the default suggestion because Chrome-family browsers trigger a macOS
   keychain prompt on every read.
3. Add to `config.toml`: `[media]` / `cookies_from_browser = "firefox:pith"`.

Cookies are used only for `cookie_domains`, fetches to those hosts are spaced `cookie_gap_seconds` apart and the
requests inside one fetch are slowed (`--sleep-requests 1`). If the session expires or the account gets a
checkpoint, the item falls back to the clarification and says so ("your browser session ... may have expired");
log in again in that profile and `pith retry <id>`. Reels have no caption track, so a transcription backend is
still required. Not verified against the real sites (see `docs/limitations.md`); Instagram can change this at any time.

## `[backends.NAME]`

`NAME` is yours. `type` selects the implementation; the other keys depend on it. Unknown types, missing
required keys and unknown task references fail at load with a message naming the backend.

Common: `type`, `locality` (`local` or `remote`; anything else is a config error), `timeout` (seconds; a positive number, otherwise a config error), `context_window` (a positive integer, same rule).
When `locality` is absent: an `openai_compat` backend is `local` only if its `base_url` host is loopback
(`localhost`, `127.0.0.0/8`, `::1`) and `remote` for every other host; a `cli` backend is `local`
(a command cannot be inspected). An explicit `locality = "local"` on a non-loopback `openai_compat` host
is honoured (a LAN server you trust), and `pith doctor` warns about it.

| `type` | Keys |
|---|---|
| `heuristic` | none |
| `openai_compat` | `base_url`*, `model`*, `api_key_env`, `embed_model`, `capabilities` (list from `json_mode`, `vision`, `rerank`, `transcribe`, `embeddings`; `text` is always on; `embeddings` needs `embed_model`; `ocr` is rejected because no OpenAI-wire OCR call exists), `transcribe_model`, `vision_model`, `rerank_model` (each defaults to `model`), `context_window`, `locality`, `timeout` (120) |
| `cli` | `command`* (list of strings), `prompt_via` (`stdin` default, or `arg`: prompt appended as the last argument), `capabilities` (only `text` and `json_mode` are accepted), `context_window`, `locality`, `timeout` (300) |
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
| `PITH_HOME` | Home directory (see precedence above) |
| `PITH_CONFIG` | Config file path, used when `--config` is not given |
| `PITH_HTTP_TOKEN` | Overrides `[http] token` |
| `PITH_YT_DLP`, `PITH_FFMPEG` | Override `[media]` executables |
| the variable named by a backend's `api_key_env` | API key for that backend |
| `PITH_LIVE_CHAT_MODEL`, `PITH_LIVE_EMBED_MODEL`, `OLLAMA_HOST` | Tests only, see [testing.md](testing.md) |

## Command-line flags that are not in the file

`--home` and `--config` (global); `search --mode {fts,hybrid} --limit N`; `ask --k N --json`;
`doctor --full --json`; `egress --json`; `digest --since --dry-run --force`; `export --keep`;
`reindex --prune-old`; `run --port --no-dashboard --no-watch`. Use `pith <command> --help`.

A configuration problem (missing `--config` file, TOML syntax error, a value of the wrong type such as a string for
`[watch] dirs` or a number for a task route, an unknown backend `type`, a bad spec or a task naming an unknown
backend) ends every command with one `error: ...` line and a non-zero exit, never a traceback.
