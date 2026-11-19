# Roadmap

## Vision

Saving something should cost nothing: you see a reel, a thread, a video or an article, share it, and it is
handled. No filing, no categorising, no app to open. Later, you open Pith to read what matters, find any
detail, and trust what you see: every statement traces to its source, gaps and low confidence are shown, and
failures are named in plain words with a one-click fix.

Three rules hold the rest together:

- **Fully user-owned.** You run it, you own every account, key, bot and file. No relay, no shared account, no
  default third-party service, nothing "we" operate.
- **Capture is separate from reading.** Capture happens wherever you are, through one-way channels that only
  feed a queue. The dashboard is where knowledge is read, searched and reused.
- **Incomplete beats wrong.** A small local model finds facts; code verifies them against the source.

## Next steps

In rough order:

1. **Make capture solid.** Verify Instagram/TikTok through the cookie route, whisper transcription and a real
   Telegram export; show skipped or failed channel files in `pith inbox`; then more channels (email first).
2. **UI redesign by category** (see below): shelves such as entertainment, useful and reference, placed
   automatically, so you browse by what an item is for.
3. **Set up from the dashboard.** Models, transcription, OCR and channels configured in the UI, not only
   the CLI and `config.toml`.
4. **Better notes on small hardware.** Tune and benchmark note-v1 on real saved content, and on the smaller
   local models that fit a laptop's memory.
5. **Reach it from anywhere.** A safe way to read and search from your phone, still self-hosted (the
   bot as a read-only view is one option).
6. **Use your existing AI subscription.** The deferred V2 work below: Claude/Codex/Gemini through an
   unattended daemon, plus an MCP server so an assistant can search your notes.

## UI redesign: organise what you save by what it is for

Status: backend for shelves and placement is built (shelf columns, placement stage, `/api/shelves`, `?shelf=`, move via `PATCH /api/items/:id`); the dashboard now reads and writes all of it through the API (only which built-in shelves you hid and the collapsed sidebar stay in the browser). Per-note state (done, snooze, hide, last viewed), entries and explainable resurfacing (`/api/resurface`, also the digest) are built too. Original idea: A large UX/UI piece of work, to be shaped before any code.

### Problem

Today the Library is one list of notes with automatic topics. That does not match how people think about what
they save. A movie to watch, an album to listen to and a GitHub repo to try are different kinds of things, read
at different moments, with different next actions. A single list mixes them, and "find it later" turns into
scrolling.

### User stories

- Evening on the sofa: "I want something to watch": I open Pith and see only movies and shows I saved, not
  articles.
- At the desk: "what tools did I want to try?": I see repos, apps and sites I saved, with what each one does.
- Saving is unchanged: I share a link and do not choose a category. Pith places it and I can correct it in one
  click.
- A reel naming five films becomes five entries I can tick off, not one blob of text.
- I can mark something done (watched, read, tried) and it moves out of the way without being deleted.
- Months later, search still spans everything, whatever shelf it sits on.

### Proposed model (to confirm)

- **Shelves, two levels deep at most.** A small set of built-in top-level shelves, each with types inside:
  - *For fun*: movies and shows, music, books, games, places.
  - *Useful*: articles to read, tools and repos, sites and resources, how-tos and recipes.
  - *Reference*: things to keep and look up (facts, documents, screenshots).
- **Placed automatically.** The note pipeline already reads the source; it also proposes a shelf and type.
  The user never files anything (this follows the vision), but can move an item, and the correction is
  remembered.
- **Built-in shelves plus your own (decided).** Sensible defaults so the first run is not an empty setup
  screen, and people can create, rename, hide, merge and delete shelves from the start. A shelf you create
  has a name and one line saying what belongs in it; that line is what the classifier reads.
- **An "Other" shelf (decided).** Anything the classifier is not confident about lands in a generic *Other*
  shelf instead of being forced into a wrong one. It is built in and cannot be deleted. Items there are shown
  as "needs a home" with one-click move, so nothing is hidden and a wrong guess never looks certain. Deleting
  a shelf moves its items to Other, and adding a shelf offers to re-check what is in Other.
- **Topics stay.** Shelves answer "what is this for"; topics answer "what is it about", and cut across shelves.
- **A state per item** where it makes sense: to do, done. Watch/read/try lists need it; reference does not.

### Open questions

- Are the shelves above right, and is two levels enough? (Games under "for fun" versus a "games to play"
  shelf; recipes under "useful" versus their own.)
- One item in two shelves (a documentary that is also learning material), or exactly one with topics for the
  rest?
- Where is the confidence threshold for Other? Too low and Other stays empty with wrong guesses on the
  shelves; too high and everything lands in Other. It is set from the classifier benchmark, not guessed.
- Classifying against a closed list that includes the user's own shelves: how many shelves can a small local
  model handle reliably before accuracy drops?
- What happens to the existing notes: backfill by reprocessing, or only new items?
- Lists inside one source (five films in one reel): split into separate entries, or one entry with a
  checklist?
- Navigation: shelves as the left sidebar replacing the Library, or a layer above it? How does it sit with
  Today, Inbox, Search and Ask?
- Mobile first: is this how you browse on a phone, and does the Telegram bot get a read-only view of a shelf?

### Work

1. Research and user stories with real saved content: what do ~100 saved items actually split into?
2. Information architecture: shelves, types, states, one item or many placements.
3. Classification: the note pipeline picks a shelf and type from the closed list of current shelves (built-in
   and the user's), or Other when unsure. Benchmark accuracy and the Other threshold on real items before any
   UI depends on it; the classifier also has to work with a shelf the user just invented.
4. Wireframes and a clickable prototype, desktop and phone, tested on real data.
5. Implementation: schema (shelf, type, state), migration of existing notes, dashboard views, correction flow.
6. Shelf-aware search filters and `pith` commands.

## Backlog

Gaps consciously left out, roughly in order of usefulness. Not a commitment.

## Verify first

- A real whisper.cpp transcription run, a real Telegram Desktop export, and Instagram/TikTok fetching through
  the opt-in browser-cookie route (all tested only against fakes).
- Cloud backends with real credentials, and a larger local model than `gemma4:e4b`.
- Near-duplicate thresholds tuned against a real embedding model.

## Capture

- More channels on the existing `Channel` protocol (email, others). Telegram is the first.
- A browser extension that posts to the local endpoint.
- Make skipped or failed channel files (for example Telegram files over 20 MB) visible in `pith inbox`.
- A setup screen in the dashboard (setup is CLI-only today).

## Reading and search

- OCR for scanned PDFs; non-English captions; subfolders in the drop folder; streaming parse of very large
  Telegram exports.
- A CLI option for filtering search (filters are dashboard/API only today).
- Approximate nearest-neighbour search (for example `sqlite-vec`) past roughly 200k chunks; a shortlist for
  duplicate detection (linear per new item today).
- Native `trafilatura` extraction (optional extra) for harder pages.

## Safety and operations

- An SSRF allow/deny policy for submitted URLs and a guard on public-to-private redirects.
- Move the restore guard into `backup.restore` itself and make `run` hold the shared `in-use.lock`.
- A backup escape hatch when one live blob is corrupt (skip and report).

## Deferred to V2: subscriptions and host-agent mode

The MVP targets API keys and local models only. Built but not part of the MVP promise and not to be extended
until V2: the `claude_sub` / `codex_sub` cli presets, the dashboard "Use my subscription" panel, and
host-agent mode (`host-prompt`, `host-apply`, `ask --retrieval-only`, `skill/SKILL.md`). They sit behind the
provider ports and the CLI, so nothing else depends on them. V2 plan: an unattended daemon spawns the
subscription CLI per item, with an MCP server for the interactive side.

## Non-goals

Multi-user, sync and hosting. Pith is fully user-owned: no relay, shared account or default third-party
service.
