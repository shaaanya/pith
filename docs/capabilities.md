# What Pith can do

## Capture: ways to send it something

| Way | What it is | Good for |
|---|---|---|
| Telegram bot | A bot you create yourself; share a link or file to it from any device | Saving from your phone, away from your computer |
| Drop folder | Put a file, `.url`, `.webloc` or a text file of links in `<home>/inbox` | Files, iCloud/Dropbox-synced folders |
| Dashboard | Paste, drop or attach anywhere on the page (press `n`) | Saving from the laptop |
| CLI | `pith submit "<url or text>" --why "..."` or `--file PATH` | Scripts and terminals |
| HTTP endpoint | `POST /v1/inbox` with a token (`pith serve-http`) | iOS Shortcut, bookmarklet, your own tools |
| Telegram export | `pith import-telegram result.json` | Backfilling an old chat |

Every way goes through the same single entry point, the inbox, so they all behave alike: the same item is
never saved twice, and a failed item keeps its original. Details in [inbox-contract.md](inbox-contract.md).
Channels only receive: they never reply to what you send.

## Read: what it understands

| Input | How |
|---|---|
| Web pages, articles, Reddit threads | Fetched and reduced to the main text (no JavaScript rendering) |
| PDF | Text per page (scanned PDFs need clarification: no PDF OCR yet) |
| Word, PowerPoint, Excel | Text extraction |
| Images, screenshots | OCR (tesseract), or a vision model if you configure one |
| YouTube and other video | Existing English captions first; transcription (whisper.cpp) only if there are none |
| Audio and voice notes | Transcription (whisper.cpp) |
| Instagram, TikTok | Usually login-walled. Optional: reuse a throwaway account's browser cookies ([configuration.md](configuration.md#instagram-and-tiktok-login-walled-links)) |
| Plain text, code, notes | Stored as written |

When Pith cannot read something it says so in plain words and asks you for help (paste the transcript,
attach the file) instead of guessing.

## Understand: one note per source

Each source becomes one note that holds the actual information (steps, numbers, names, resources, warnings),
not a description of it. Every statement points back to the part of the source it came from. A fact the
source does not support is dropped; your reason for saving is used only if you wrote one. Topics and entities
are assigned automatically; you can edit, reprocess or delete a note, and edits are versioned. How it works:
[pipeline.md](pipeline.md).

## Use: find and recall

- **Search**: full-text, plus meaning-based search when an embedding model is configured.
- **Ask**: `pith ask "..."` or the Ask box answers from your notes only, with numbered citations; with no
  answer model it shows the matching excerpts instead.
- **Library and Today**: browse by date and topic; near-duplicates are linked, never merged or deleted.
- **Digest**: `pith digest` writes a daily summary of what arrived.
- **Export**: `pith export` writes a plain Markdown vault (frontmatter plus body) you can open anywhere.

## Run it your way

- **Models are optional.** With none, a deterministic fallback still stores and searches. Local models
  (Ollama, whisper.cpp, tesseract) and API-key cloud models plug in per task; see [backends.md](backends.md).
- **Local by default.** Text leaves your machine only if you allow remote models, and `pith egress` shows
  exactly what was sent.
- **Yours.** One folder, SQLite plus plain files. `pith backup`, `pith verify` and `pith restore` protect it;
  `pith doctor` checks health.
