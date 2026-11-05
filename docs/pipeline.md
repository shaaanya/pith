# Processing pipeline

A worker claims a job and calls `pipeline/runner.py:process(services, inbox_id)`. The stages, each recorded
as a `processing_events` row:

    detect -> extract -> chunk -> distill -> save -> entities/topics -> embed -> dedupe/relate

`process` is idempotent per inbox id: reprocessing replaces the non-user-edited items of the same source
(old versions are kept in `knowledge_versions`). The last three stages are best-effort: a failure is logged as
an error event and never fails the item.

## detect

Chooses a content type from the URL host/extension, then the file name extension, then magic bytes, then
the MIME type: `web`, `video`, `audio`, `pdf`, `image`, `document` (docx/pptx/xlsx), `text`, `code`,
`note`. Hosts youtube.com, youtu.be, instagram.com, tiktok.com and vimeo.com are `video`. A content type
with no registered extractor ends in `needs_clarification`.

## Extractors (`pipeline/extractors/`)

| Type | How | Limits |
|---|---|---|
| `web` | `urllib` fetch with a User-Agent, 20 s timeout, byte cap `max_fetch_bytes`; main-content extraction with the stdlib `html.parser` (no `trafilatura`); headings, title and author kept. Reddit thread URLs use the public `.json` endpoint. | Canonical URLs are `https`; if the TLS connection fails the URL is retried exactly as submitted (this is how a local `http://` server works). Paywall/login pages, HTTP errors that look like walls, PDFs and other non-page content types go to `needs_clarification`. No JavaScript rendering. Robots rules are not consulted. |
| `pdf` | `pypdf` if installed, else `pdftotext`; one section per page, locator `page=N`. | Scanned PDFs (no text layer) go to `needs_clarification`; there is no PDF OCR. The `pypdf` path is not exercised by the verification here (only `pdftotext`); see [limitations](limitations.md). |
| `document` | docx, pptx, xlsx via `zipfile` + `ElementTree`. | Text only. docx sections share one locator, xlsx ignores cell references. |
| `image` | Text from the first `ocr` backend (a `tesseract` backend), else from a `describe` (vision) backend that transcribes and describes the image. | Neither backend configured, or no text found, goes to `needs_clarification`. |
| `video` / `audio` | `yt-dlp` metadata and existing captions first (VTT to timed text, nothing downloaded). Only when there are no captions AND a `transcribe` backend exists is audio downloaded and transcribed. Local audio/video files go to the transcriber after `ffmpeg` converts to 16 kHz mono wav. Frames (`ffmpeg`, 1 per 3 s) go to a `describe` backend only if one is configured and the transcript is under 200 characters. Segments carry `t=start-end` locators. Temporary media is deleted. | Captions are English only (`en`, `en.*` tracks). Instagram and TikTok usually need cookies and fail into `needs_clarification` carrying the page caption when reachable. Real transcription and real Instagram/TikTok behaviour are UNVERIFIED. |
| `text` / `code` / `note` | The text itself (UTF-8, with replacement for bad bytes). | Empty text goes to `needs_clarification`; files over `max_fetch_bytes` too. |

An extractor that needs input from you raises `NeedsClarificationError(reason)`; any other exception
becomes a failed attempt (retried with backoff, original preserved). External tools are called with
argument lists (no shell) and timeouts.

## chunk

Text is split on headings and blank lines into segments of at most 1200 characters (100 characters of
overlap when a block is split); timed text into windows of at most 800 characters. Each segment keeps a
locator: `char=a-b`, `page=N`, `t=start-end` (seconds). Segments are the unit for full-text and vector
search and the target of citations. Identical extracted text across inbox items is detected here by
`text_sha256` and shares one source.

## distill

`pipeline/distill.py` asks the `distill` task chain for structured JSON in one of five profiles
(`generic`, `article`, `programming`, `paper`, `collection`), chosen from the content type and keywords in
your context ("top 10", "list of", "paper", "code"...). For each backend in the chain:

1. Generate with the schema in the request (as `response_format` if the backend declares `json_mode`, else
   in the prompt text).
2. Parse (bare JSON, a fenced block, or the first JSON object embedded in prose; control characters inside
   strings are tolerated; the scan is bounded to the first 256 KB and 200 start positions). Validate
   against the profile schema. Empty summaries, empty item text/title, empty snippet code, an empty
   collection title or entry name are invalid.
3. On failure, one repair request that quotes the error. On a second failure, the next backend.
4. The `heuristic` backend is always last: it picks the highest-scoring sentences, so a result is always
   produced even with no model.

Input longer than the backend's `context_window` is map-reduced (batches, then merged items and a combined
summary). The output is normalised into candidates (`summary`, `insight`, `claim`, `snippet`, `collection`
...), then passes the provenance check. The backend that produced the result is stored in
`knowledge_items.extracted_by` as `backend:model`.

## Provenance

Each item has `provenance`:

- `stated`: the source says it, and the item carries an `evidence` quote.
- `inferred`: a model's reading or summary, not a direct quote.
- `external`: something from outside the source; requires a URL.

Downgrade rule (`pipeline/provenance.py`, domain-enforced and unit-tested): a `stated` item must reference
a segment, and its quote must be a substring of that segment after whitespace and case normalisation.
Otherwise it is stored as `inferred` with `data.flag = "evidence_not_found"`. An `external` item without a
URL becomes `inferred`. The check never invents evidence; it only downgrades. Collections and summaries
have no quote and are `inferred`.

What this does and does not guarantee: a stored `stated` item's quote does occur in the cited segment.
It does not guarantee the item's wording is a faithful reading of the quote.

## save, entities, embed, dedupe

- Source, segments and items are written in one transaction (FTS rows in the same transaction). Items that
  you edited (`user_edited`) are preserved on reprocess.
- Topics and entities are normalised (case-folded, trimmed) and stored in `topics`, `entities`,
  `item_topics`, `item_entities`. There is no alias table.
- Embeddings are computed for new items and segments when an `embed` backend exists; the vector's
  `model_id` comes from the backend. Without one, this is a no-op and FTS still works.
- Near-duplicate and related detection writes `relations` (see [inbox-contract](inbox-contract.md#duplicates)).
  It compares each new item with all live items, which is linear in the library size.

## Retrieval

`infoparser search` runs SQLite FTS5 (BM25) over items and segments, and, if an embedding backend is
configured and vectors exist for the active model, cosine similarity over items and segments (brute force,
numpy). The lists are fused with reciprocal rank fusion (k = 60), capped at two hits per source, and
optionally reranked by a `rerank` backend. The result states its mode, `hybrid` or `fts`; a failing optional
stage degrades to `fts` with a warning, it does not raise. Soft-deleted items are never returned. The CLI
has no filter flags; the dashboard API supports filters `kind`, `provenance`, `platform`, `topic`.

`infoparser ask` retrieves, then asks the `answer` chain (heuristic excluded, it cannot answer) to answer
only from numbered excerpts. Retrieved text is delimited and labelled as untrusted data. Every `[n]`
marker is validated: markers naming a nonexistent excerpt are removed and reported; if no valid marker
remains the generated text is discarded and the result is `retrieval-only` with the excerpts. With no
answer backend the result is also `retrieval-only` with a message. The prompt-injection defence is
delimiting plus validation, not proof (see [limitations](limitations.md)).
