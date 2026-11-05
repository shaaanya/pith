# Data model

SQLite, schema version 3 (`PRAGMA user_version = 3`). Migrations are numbered SQL files in
`src/infoparser/store/migrations/`: `001_init.sql`, `002_external_id.sql`, `003_external_ids.sql`. The
migration splitter is simple: no triggers in migration SQL. Ids are 26-character, time-sortable strings
(`ids.new_id()`); timestamps are UTC ISO-8601 `YYYY-MM-DDTHH:MM:SSZ`.

## Tables

| Table | Purpose |
|---|---|
| `inbox_items` | One row per submission: `id`, `adapter`, `platform`, `submitted_at`, `kind_hint`, `content_type`, `payload_text` (URL or note text), `blob_sha256`, `original_filename`, `mime`, `canonical_url`, `user_context`, `status` (CHECK: new, pending, processing, processed, failed, needs_clarification), `error`, `attempts`, `duplicate_of`, `source_id`, `updated_at`, `external_id`. Unique index on `canonical_url` (where `duplicate_of` is null) and on `(adapter, external_id)`. |
| `external_ids` | `(adapter, external_id) -> inbox_id`, the idempotency record for adapters (migration 003). |
| `jobs` | Queue: `inbox_id`, `kind`, `state` (pending, running, done, failed), `attempts`, `run_after`, `lease_expires_at`, `worker_id`, `last_error`. |
| `processing_events` | History: `inbox_id`, `at`, `stage`, `status`, `detail`, `duration_ms`, `backend`, `model`, `egress` (1 when text was sent to a remote backend). Also stores `clarified` and `duplicate` events. |
| `sources` | One per extracted origin: `url`, `title`, `author`, `platform`, `content_type`, `fetched_at`, `blob_sha256` (original), `text_sha256` (normalised extracted text), `extractor`. Several inbox items can map to one source. |
| `segments` | Chunks of a source: `source_id`, `idx`, `text`, `locator` (`char=a-b`, `page=N`, `t=start-end`). Unique `(source_id, idx)`. |
| `knowledge_items` | The distilled items: `kind` (summary, insight, claim, snippet, collection...), `title`, `body`, `data_json` (kind-specific data, evidence quote, flags), `provenance` (CHECK: stated, inferred, external), `confidence`, `source_id`, `segment_refs`, `extracted_by`, `user_edited`, `version`, `flagged`, timestamps, `last_viewed_at`, `deleted_at` (soft delete). Index on `source_id`. |
| `knowledge_versions` | Previous title/body/data on edit or reprocess, with a reason. |
| `topics`, `entities`, `item_topics`, `item_entities` | Normalised names and their links to items. These tables are the source of truth for topics/entities. |
| `relations` | `(item_a, item_b, type, score)`, type `duplicate` or `related`. |
| `embeddings` | `(owner_type, owner_id, model_id)` primary key, `dim`, float32 `vector` BLOB. Vectors for a different `model_id` than the active one are ignored. |
| `provenance_log` | Every submission that maps to a source: `source_id`, `inbox_id`, `url`, `added_at`. |
| `segments_fts`, `items_fts` | FTS5 virtual tables. Plain (not external-content): rowid equals `segments.id` / the item's rowid and is maintained in the same transaction as the writes. |

## Not in the database

- Original files: `<home>/blobs/<ab>/<cd>/<sha256>`, referenced by `blob_sha256`.
- The vault: `<home>/vault/<yyyy>/<slug>-<id>.md`, derived. Each file has a frontmatter block (`id`,
  `kind`, `title`, `provenance`, `source_url`, `source_title`, `created`, `updated`, `topics`, `entities`,
  `locators`) written as JSON scalars, then the body and a quoted source section.
- The ingest token: `<home>/http_token` (excluded from backups).
- Digests: `<home>/digests/YYYY-MM-DD.md`; backups: `<home>/backups/` by default.

## Embedding model switches

Changing the configured embedding model changes the `model_id`; old vectors stay but are ignored, search
falls back to FTS until `infoparser reindex` has embedded under the new model. `reindex --prune-old`
removes vectors of other models. Vectors are never required for correctness.

A segment's vectors are deleted in the same transaction that changes or removes its text (reprocess), and
the next embedding pass refills the changed ones, so a vector never outlives the text it encodes.
