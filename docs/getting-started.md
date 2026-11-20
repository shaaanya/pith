# Getting started

You need Python 3.13 and [uv](https://docs.astral.sh/uv/). Everything Pith stores lives in one folder
(`~/Pith` by default, change it with `PITH_HOME`).

## 1. Install and start

```
git clone https://github.com/shaaanya/pith && cd pith
uv tool install --editable .      # puts `pith` on your PATH (or use `uv run pith` inside the repo)
pith init                         # creates the folder; in a terminal it offers the channel setup (step 3)
pith                              # same as `pith run`: worker + dashboard + enabled channels
```

`pith` prints the dashboard address (loopback only, with a token). Open it, press `n` and paste a link or a
note. It works at once with no model: Pith stores and searches the text with a deterministic fallback.

The V5 dashboard opens on **Your Working Desk**. Use **New group** to choose notes from your real library,
then open groups independently. Group options let you edit membership or add a context to **Focus**;
**Arrange** changes their order, and **Undo last change** reverses the last organization change. Groups
and Focus are saved in the Pith database across browser and app restarts. Removing a group keeps its
notes. Recently saved and All knowledge remain available before you organize anything.

To stop the running app from another terminal:

```sh
pith stop
pith stop --home /path/to/Pith       # use the same home as the running instance
pith stop --timeout 120              # allow more time for active work to finish
```

`pith stop` shuts down bare `pith` / `pith run`: its dashboard, worker and enabled channels. It waits
up to 30 seconds and reports success only after those threads finish. If a job takes longer, the
command reports that shutdown is still in progress; it does not kill the job. A repeated stop is safe
and says “not running” when the instance is already stopped. Ctrl-C in the original terminal also
requests clean shutdown. Use the matching `--home` or `--config` for a nondefault home; an explicit
`--home` works even with a broken config file.

Separately launched `pith worker`, `watch`, `dashboard`, `serve-http`, frontend development and prototype
servers remain separate processes; stop them in their own terminals with Ctrl-C. Instances started
with an older version without shutdown metadata need Ctrl-C once, then can use `pith stop` after restart.

## 2. Add a model (optional, recommended)

A model is what turns a source into a good note. Pith is tuned for a small local model, `gemma4:e4b` via
[Ollama](https://ollama.com), but any OpenAI-compatible server or an API key works.

- Dashboard: **Settings → Add a local model / Add a cloud (API key) model**, then pick it under
  "What each job uses".
- Or edit `<home>/config.toml` (start from `config.sample.toml`):

```toml
[backends.local]
type = "openai_compat"
locality = "local"
base_url = "http://localhost:11434/v1"
model = "gemma4:e4b"
embed_model = "nomic-embed-text"      # optional: meaning-based search
```

Optional extras: `tesseract` for images and `whisper.cpp` for audio and video without captions
(`[backends.ocr]`, `[backends.stt]`; see [configuration.md](configuration.md)). Cloud backends are refused
until you set `[privacy] allow_remote = true`.

## 3. Save from your phone (Telegram bot)

1. In Telegram, talk to @BotFather, create a bot, copy the token. You own the bot; nothing runs on anyone
   else's server.
2. `pith setup`: paste the token (hidden), it is checked and saved (`<home>/telegram_token`, never in
   `config.toml`), and a one-time pairing code is printed.
3. `pith` (or restart it), open your bot, press Start, send the code. From then on, share any link, note,
   file, photo or voice message to the bot. It never replies to content; the item appears in the
   dashboard's Inbox and becomes a note.

Other ways to capture (drop folder, HTTP endpoint for an iOS Shortcut, CLI): [capabilities.md](capabilities.md).

## 4. Use it

```
pith submit "https://…" --why "the pricing table"   # --why is optional, and used only as you wrote it
pith search "keywords"
pith ask "what did that video say about …?"          # answers from your notes, with citations
pith inbox                                           # what is waiting or needs your help
pith doctor                                          # health check
pith backup                                          # copy your data; `pith verify` / `pith restore`
```

If something shows "Needs you", Pith could not read it (a login wall, an image with no OCR, a video with no
captions). Add what it asks for in the dashboard, or `pith clarify`, and it continues.
