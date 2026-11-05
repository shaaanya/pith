# Roadmap

Nothing here is built. These are the gaps that were consciously left out, roughly in order of usefulness,
not a commitment. Verification gaps are in [limitations.md](limitations.md).

- Verify the unverified paths first: a real Telegram export, a real whisper.cpp run, cloud backends with real
  credentials, a larger local model, and tuning the near-duplicate thresholds against a real embedding model.
- A CLI option for filtering search (`clarify` exists; filters are dashboard/API only).
- Move the restore guard (`locks.restore_guard`) into `backup.restore` itself and make `run` hold the shared
  `in-use.lock` too, instead of relying on the CLI wrapper and `run.lock`.
- OCR for scanned PDFs; non-English captions in the media extractor; recursion into subfolders in the drop
  folder; streaming parse of very large Telegram exports.
- An escape hatch for backup when one live blob is corrupt (skip and report), and `.pre-restore` path in
  the error when a rollback rename fails.
- Approximate nearest-neighbour search (for example `sqlite-vec`) once the library passes roughly 200k
  chunks; an LSH shortlist for duplicate detection (it is linear per new item today).
- Native `trafilatura` extraction (optional extra) for harder pages, and a browser extension that talks to the
  local endpoint.
- An email adapter and a shipped Telegram bot adapter (a recipe exists).
- An SSRF allow/deny policy for submitted URLs and a guard on public-to-private redirects.
- Multi-user, sync and hosting are non-goals.
