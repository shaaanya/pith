# Inbox contract

Everything that enters the system goes through `Inbox.submit()` (`src/pith/inbox/service.py`).
Adapters never touch the database or the blob store themselves.

Channels (`pith/adapters/base.py`) are the long-running adapters: `name`, `interval` and `poll() -> int`, run by
`run_channel` with error backoff and status in `channel_state`. Channels are one-way: they only submit (the Telegram pairing handshake is the one exception).

## Submission

`submit(adapter=..., text=... | file=..., filename=, mime=, user_context=, platform=, external_id=)`:
exactly one of `text` or `file`.

- `text` that is a single `http(s)://` URL becomes a URL submission (`kind_hint = url`; the URL is kept exactly as
  submitted in `payload_text`, and the canonical form is stored only as the dedupe key). Any other text is a note (`kind_hint = text`) and is never deduplicated.
- `file` (path or bytes) is written to the blob store (content-addressed) and becomes a file submission.
- `user_context` is free text from you ("why I saved this"). It is passed to distillation as a hint and
  kept on the record.
- `platform` is derived from the URL host (youtube, instagram, tiktok, reddit, twitter, github, else
  `unknown`) unless an adapter supplies it.
- `external_id` is an adapter-scoped stable id (for example a Telegram message id). A repeat of the same
  `(adapter, external_id)` is a no-op duplicate.

Persistence rule: the blob, the `inbox_items` row (status `pending`) and the `jobs` row are written in one
transaction before `submit()` returns. No extraction code runs in the submit path. The result is
`SubmitResult(id, duplicate_of, requeued)`.

## States

| Status | Meaning |
|---|---|
| `new` | Defined in the enum and the schema CHECK. The current code never assigns it: `submit()` inserts `pending` directly. |
| `pending` | A job is queued, or waiting for a retry after a failed attempt. |
| `processing` | A worker holds the job's lease. |
| `processed` | Extraction and distillation finished; items are stored. |
| `failed` | The job used all `max_attempts`, or its lease expired after the last attempt. The original blob/URL is kept and the error is stored. |
| `needs_clarification` | The system cannot proceed without you (paywall or login wall, empty text, image with no text, URL that serves a PDF or other non-page type, over the size cap, no OCR or no PDF reader installed). The reason is stored in `error`. |

Transitions: `pending -> processing -> processed | failed | needs_clarification`. A failed attempt that has
attempts left goes back to `pending` with a backoff `run_after`. `retry` and `clarify` move a
`failed`/`needs_clarification` item back to `pending`.

Every stage writes a row to `processing_events` (stage, status, detail, duration, backend/model, whether
text left the machine). `pith show <inbox id>` prints the status, error, context, stored items and
events.

## Retry and clarification

- `pith retry <inbox id>` re-queues an item (attempts reset to 0, error cleared). A job is only
  inserted if none is pending or running for that item. Unknown ids are an error.
- Clarification (`Inbox.clarify`, dashboard "clarify" box) appends your text to the item's context, records
  a `clarified` event and re-queues. If the extractor failed on something pasted text can solve (a login
  wall, an empty text, an image with no text), your latest clarification becomes the content: the stored
  source is a note with extractor `user_clarification` and no URL, with a `user_text` event naming the
  original URL. For problems that pasted text cannot solve (file over the size cap, no PDF reader) the
  original reason is kept. The submit-time `--context` is never treated as pasted content.
- CLI: `pith clarify <inbox id> <text...>` does the same as the dashboard box.

## Duplicates

- Same canonical URL: URLs are canonicalised (scheme forced to `https`, `www.`/`m.` prefix removed, host
  lowercased, tracking parameters such as `utm_*`, `fbclid`, `gclid`, `igshid`, `si` removed, query sorted,
  trailing slash removed, `youtu.be/x` rewritten to `youtube.com/watch?v=x`). A second submission returns
  the existing inbox id with `duplicate_of` set, appends your new `user_context`, and adds a
  `provenance_log` row. No new inbox row.
- Same file bytes: same rule, keyed on the blob SHA-256.
- Resubmitting a `failed` or `needs_clarification` item re-queues it (with the new context attached)
  rather than folding into a dead record.
- Same extracted text through a different URL: the later inbox item ends `processed`, shares the first
  item's source (`source_id`), gets a `duplicate` event naming the original, and adds a `provenance_log`
  row. List all submissions of a source with
  `SELECT inbox_id, url, added_at FROM provenance_log WHERE source_id = ? ORDER BY id`.
- Near-duplicate knowledge items (similar but not identical text) are linked in `relations` with type
  `duplicate` or `related`; nothing is merged or deleted. Thresholds: cosine 0.92 / 0.75 with embeddings,
  shingle Jaccard 0.8 without (the cosine thresholds are UNVERIFIED against real models, see
  limitations).
- Plain notes are never deduplicated.

## Adapters

All adapters report the same shape of result and differ only in how they obtain the payload.

### CLI

`pith submit "<url or text>" [--context TEXT]` or `pith submit --file PATH [--context TEXT]`.
Prints `submitted <id>`.

### Drop folder (`fs`)

`pith watch [--once]` or the watcher inside `pith run`. Watches `[watch] dirs` (default
`<home>/inbox`). A file is submitted only if it is not hidden, not an `.icloud` stub, not `.part`/`.tmp`/
`.crdownload`, not a symlink pointing outside the folder, within `max_fetch_bytes`, older than 2 seconds,
and unchanged in size across two polls. After `submit()` returns the file is moved to `<dir>/.processed/`.
`.url`, `.webloc`, and `.txt`/`.md` files whose every non-empty line is a URL become one URL submission per
URL. It does not recurse into subfolders. `watch --once` polls twice; files modified in the last 2 seconds
are skipped, so run it again if a file was just written.

### Telegram Desktop export

`pith import-telegram <result.json> [--since DATE] [--fetch-urls]`. URL-only messages are kept as
notes (URL verbatim, not fetched) unless `--fetch-urls`, which fetches them as untrusted: public addresses only.
One message becomes one submission
(`adapter = telegram_export`, external id `<chat id>:<message id>`), so re-importing is a no-op. Prints
`submitted N, duplicates N, skipped N`. UNVERIFIED against a real export: it follows the documented
`result.json` shape and was tested on a hand-built fixture. The whole JSON is read into memory.

### HTTP ingest

`pith serve-http` listens on `[http] bind:port` (default `127.0.0.1:8787`).

| Request | Notes |
|---|---|
| `POST /v1/inbox` with `Content-Type: application/json` and body `{"url": ...}` or `{"text": ...}`, optional `"context"`, `"platform"` | exactly one of `url` (must be http/https) or `text` |
| `POST /v1/inbox` as `multipart/form-data` | a file part plus optional `context`/`platform` fields |
| `POST /v1/inbox` with a raw body and any other content type | the body is the file; filename from the `X-Filename` header, context from `X-Context` |
| `GET /v1/inbox/<id>` | `{id, status, error, content_type}` |

The response to a POST is `{"id": ..., "status": ..., "duplicate": true|false}`. `Content-Length` is
required and bodies over `max_fetch_bytes` get 413. Other methods get 405.

Authentication is always required: `Authorization: Bearer <token>` or `X-Token: <token>`. The token is
`[http] token` / `PITH_HTTP_TOKEN` if set, otherwise it is generated into `<home>/http_token`
(mode 0600) the first time the server (or dashboard) starts. A non-loopback `bind` is refused unless a token
is set explicitly. There is no TLS. See deployment.md for the security model and
recipes for clients.

### Dashboard

The "add" box in the dashboard calls the same `Inbox.submit()`.
