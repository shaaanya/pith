# Pith Home V4: the memory desk (prototype notes)

Prototype: `prototype/index.html`. Open `?data=S|R|E&pins=none|notes|mixed|many&theme=light|dark`, or use the Prototype popover.
Pins live in this browser's localStorage only. The backend has no pins today.

## 1. Home architecture (top to bottom)

| Level | Section | Job | Source of truth |
|---|---|---|---|
| Command | Find/Ask + Save (top bar), capture chip | Find, save, see capture health | existing |
| Header | "Your Pith" + one chip | `Capture active`, or `N captures need attention · Review` (expands in place) | failed jobs |
| A | **Pinned to your desk** | Things the user chose to keep in reach | user pins (persist until removed) |
| B | **Pith brings forward**: Worth remembering + Pick up | Pith's explainable resurfacing; real unchecked entries | `resurface.py`, `entries` |
| C | **Fresh from Pith** | Extracted substance from recent captures (a fact or command), source secondary | newest notes' key points |
| Exit | Topic chips | Compact entry points | note topics |

Rules kept: no note/point appears twice on Home; a pinned note or point leaves B and C; shelves stay in the sidebar only; Pith never pins for the user; unpinning never touches the note.

Responsive (container queries on the content width, not the viewport):
- 4 columns at ≥72rem (cap 8 cards), 3 at ≥56rem (cap 6), 2 at ≥40rem (cap 4), 1 below (cap 3).
- "View all N" appears only when cards are actually hidden.
- Brings forward sits side by side from 60rem, then stacks. At phone width: 1 resurfaced card, 3 entries, 3 fresh items.
- Mobile order: search/Save, pins (or compact intro), one resurfaced item, Pick up, Fresh, topics.

## 2. Pin types (inferred, never chosen)

| Pin | Created from | Card shows | Actions |
|---|---|---|---|
| Note | whole-note pin on a reference note | title, 3-line summary, shelf, source | Open |
| Fact | a key point | the statement itself | See evidence, Copy |
| Command | a key point whose item is a command | statement + monospace block | Copy command, See evidence |
| Resource | an entry, or a whole note on an action shelf (Watch, Try, Visit…) | text, "Why you saved it" (user's own words only) | tick the entry, Open |

"See evidence" opens the note and scrolls to and flashes the supporting passage (`#/note/:id?pt=i`).
A pin is not a task: only an entry pin carries a checkbox, and ticking it completes the existing entry; the pin stays.

## 3. Interaction flows

- **Pin**: reader (whole note, every key point), search result (the matched passage, else the note), shelf (note row, entry row), Pick up row, Worth remembering card, Fresh item. Toast with Undo; focus stays on the toggled button.
- **Unpin**: the filled pin on any card, or the same button where it was pinned. Undo restores the original position.
- **Annotate**: pencil → one-line input (140 chars) → Enter. Shown as the user's own words.
- **Reorder**: Arrange → arrows (keyboard and touch) or drag; announces "Moved to position n of m".
- **Copy**: command block or fact text; "Copied" toast.
- **No pins yet**: one compact row explaining pinning, linking to the latest real note. Nothing invented.

## 4. Data contracts needed (backend dependency, not built)

Verified in `src/pith/store`: key points are `knowledge_items` (id, kind, body, source_id, `segment_refs`), entries have ids, state is keyed by `owner` (source id, else note id) so it survives reprocess. There is no pin storage.

```
pins(id TEXT PK, owner TEXT,            -- same owner key as note_state, so pins survive reprocess
     target_type TEXT CHECK(IN 'note','item','entry'),
     target_id  TEXT,                   -- note id | knowledge_items.id | entries.id
     snapshot   TEXT,                   -- body at pin time, shown if the item is later removed
     annotation TEXT, position REAL, created_at TEXT)
```
- `GET /api/pins` → ordered list with the resolved target (title, body, kind, source, locator, evidence quote, entry done state).
- `POST /api/pins {target_type, target_id}` (idempotent), `PATCH /api/pins/:id {annotation}`, `PUT /api/pins/order {ids:[…]}`, `DELETE /api/pins/:id`.
- Fragment identity: key points need stable ids that survive reprocess (today a reprocess replaces the note row). Either carry `owner + normalised-body hash` like `entries.norm`, or keep the `snapshot` and show "source changed".
- The card type comes from `knowledge_items.kind` (command / fact), so no manual type choice.
- Fresh needs "best extracted item per recent note", ranked by kind (command > fact); it can be computed from existing items.
- A model "suggest a pin" hint is deferred: it would be a suggestion only, never auto-pinned.

## 5. UX problems found in review and fixed

1. Command cards stripped the command out of its sentence and left broken prose ("with the setting persists"). Now the full sentence stays and the command sits in a copyable block.
2. Key-point pin button wrapped under its text in the reader (unclosed span). Fixed; pin sits at the column edge.
3. Mobile Pick up showed 2 rows, not 3 (the section heading counted as a child in the cap). Fixed.
4. "Pinned to your desk" heading and "View all" wrapped at 390px. Tools no longer wrap and the heading shrinks.
5. "View all 12" appeared while showing all 12 at 1920px. Cap per width added; "View all" now only when something is hidden.
6. The attention bar pushed pins down. It is now a header chip that expands in place.
7. Arrange showed a "done" check while off. Now a sort icon off, check on.
8. The stats strip was removed: counts live in the sidebar, Home has no vanity numbers.

## 6. Validation

- 22 earlier behaviour checks (search, Ask, URL never auto-saves, tick, dismiss, needs-attention, theme, sidebar, mobile sheet) still pass.
- 22 new checks pass: intro with no pins, pin/unpin/Undo from reader, search, shelf, resurfaced card, Pick up entry; annotation; reorder via arrows with focus kept; persistence across reload; evidence highlight; no repeats in Fresh/Pick up/Worth remembering; "View all" visibility; Pins page; Copy toast; 320px no overflow with 12 pins; zero page errors.
- Rendered at 320/390/768/1024/1440/1920, light and dark, for none/notes/mixed/many pins on both datasets: no horizontal overflow, no console errors.

Not tested: real iOS Safari and touch drag, a screen reader pass, high-contrast mode, clipboard permission prompts outside file://.
Known caveat: rich-dataset counts (1,812 notes, 23 to do) and the "3 Postgres notes this week" reason are fixtures; pin fixtures are built from sample notes and labelled as hypothetical.
