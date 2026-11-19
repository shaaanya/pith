/**
 * Explicit, validated contracts for the Pith dashboard API (read-only reference: src/pith/dashboard/api.py).
 * The API has no OpenAPI document, so these Zod schemas are the single source of truth for types.
 * Schemas are tolerant of additions (unknown keys are dropped) but strict about what the UI relies on.
 */
import { z } from "zod";

const str = z.string();
const optStr = z.string().nullish();

export const InboxStatus = z.enum(["new", "pending", "processing", "processed", "failed", "needs_clarification"]);
export type InboxStatus = z.infer<typeof InboxStatus>;

export const InboxRow = z.object({
  id: str,
  status: InboxStatus,
  error: optStr,
  content_type: optStr,
  what: str,
  url: optStr,
  submitted_at: str,
  updated_at: optStr,
  attempts: z.number().nullish(),
  source_id: optStr,
  user_context: optStr,
  preview: optStr,
});
export type InboxRow = z.infer<typeof InboxRow>;

export const InboxList = z.array(InboxRow);

export const InboxDetail = InboxRow.extend({
  items: z.array(z.object({ id: str, title: str, kind: str, provenance: optStr })).default([]),
  events: z.array(z.object({ at: str, stage: str, status: str, detail: optStr })).default([]),
  has_blob: z.boolean().default(false),
  blob_sha256: optStr,
});
export type InboxDetail = z.infer<typeof InboxDetail>;

const PlacementBy = z.enum(["you", "model", "reason", "site", "default", "none"]).catch("none");
export const ItemPlacement = z.object({ by: PlacementBy, why: z.string().default("") });
export const ItemState = z.object({ done_at: optStr, snooze_until: optStr, hidden: z.boolean().default(false) });
const NO_STATE = { done_at: null, snooze_until: null, hidden: false };

export const LibraryItem = z.object({
  id: str,
  title: str,
  kind: str,
  lead: optStr,
  intent: optStr,
  created_at: str,
  provenance: optStr,
  confidence: z.number().nullish(),
  flagged: z.boolean().default(false),
  url: optStr,
  host: optStr,
  platform: optStr,
  type: optStr,
  topics: z.array(str).default([]),
  shelf: z.string().default("other"),
  placement: ItemPlacement.default({ by: "none", why: "" }),
  state: ItemState.default(NO_STATE),
  last_viewed_at: optStr,
});
export type LibraryItem = z.infer<typeof LibraryItem>;

export const LibraryPage = z.object({
  items: z.array(LibraryItem),
  total: z.number(),
  next: optStr,
  types: z.record(str, z.number()).optional(),
  active: z.array(InboxRow.omit({ preview: true })).optional(),
  attention: z.array(InboxRow.omit({ preview: true })).optional(),
});
export type LibraryPage = z.infer<typeof LibraryPage>;

export const Topic = z.object({ name: str, n: z.number() });
export const Topics = z.array(Topic);

const Backend = z.object({
  name: str,
  type: optStr,
  locality: optStr,
  tasks: z.array(str).default([]),
  blocked_reason: optStr,
  capabilities: z.record(str, z.unknown()).optional(),
});
export const AppState = z.object({
  counts: z.record(str, z.number()),
  jobs: z.record(str, z.number()).default({}),
  items: z.number(),
  backends: z.array(Backend).default([]),
  allow_remote: z.boolean().default(false),
  capture: z.object({ watch: z.array(str).default([]), http: str }).optional(),
});
export type AppState = z.infer<typeof AppState>;

const NoteUnit = z.object({
  type: optStr,
  text: optStr,
  support: z.number().nullish(),
  focus: z.boolean().default(false),
  locator: optStr,
});
export type NoteUnit = z.infer<typeof NoteUnit>;

export const Entry = z.object({ id: str, text: str, done_at: optStr, position: z.number().optional() });
export type Entry = z.infer<typeof Entry>;

export const ItemDetail = z.object({
  id: str,
  kind: str,
  title: str,
  shelf: z.string().default("other"),
  placement: ItemPlacement.default({ by: "none", why: "" }),
  state: ItemState.default(NO_STATE),
  last_viewed_at: optStr,
  entries: z.array(Entry).default([]),
  body: z.string().default(""),
  provenance: optStr,
  confidence: z.number().nullish(),
  user_edited: z.boolean().default(false),
  flagged: z.boolean().default(false),
  version: z.number().nullish(),
  extracted_by: optStr,
  created_at: str,
  updated_at: optStr,
  evidence: z.unknown().nullish(),
  note: z
    .object({
      units: z.array(NoteUnit).default([]),
      intent: z.object({ state: optStr, text: optStr }).nullish(),
      limits: z.array(z.unknown()).default([]),
      gaps: z.array(z.unknown()).default([]),
      dropped: z.record(str, z.unknown()).default({}),
      repairs: z.array(z.unknown()).default([]),
      stats: z.record(str, z.unknown()).default({}),
      version: optStr,
    })
    .nullish(),
  source: z.object({ id: str, title: optStr, url: optStr, platform: optStr, content_type: optStr, blob_sha256: optStr }).nullish(),
  citations: z.array(z.object({ segment_id: z.number(), locator: optStr, text: str })).default([]),
  related: z.array(z.object({ id: str, title: str, type: str, score: z.number().nullish() })).default([]),
  inbox: z.array(z.object({ inbox_id: str, url: optStr, added_at: optStr })).default([]),
  topics: z.array(str).default([]),
  entities: z.array(str).default([]),
});
export type ItemDetail = z.infer<typeof ItemDetail>;

export const SearchHit = z.object({
  item_id: optStr,
  segment_id: z.number().nullish(),
  source_id: optStr,
  note_id: optStr,
  title: str,
  snippet: str,
  source_url: optStr,
  locator: optStr,
  provenance: optStr,
  kind: str,
  score: z.number(),
});
export type SearchHit = z.infer<typeof SearchHit>;
export const SearchResult = z.object({
  mode: str,
  warnings: z.array(str).default([]),
  egress: z.array(z.unknown()).default([]),
  hits: z.array(SearchHit),
});

const Excerpt = z.object({
  n: z.number(),
  item_id: optStr,
  source_id: optStr,
  note_id: optStr,
  title: str,
  url: optStr,
  locator: optStr,
  text: str,
  kind: optStr,
  provenance: optStr,
  deep_link: optStr,
});
export type Excerpt = z.infer<typeof Excerpt>;
export const Answer = z.object({
  question: str,
  mode: str,
  retrieved: z.array(Excerpt).default([]),
  interpretation: optStr,
  citations: z.array(z.number()).default([]),
  invalid_citations: z.array(z.number()).default([]),
  deep_links: z.array(str).default([]),
  generated_by: optStr,
  retrieval_mode: optStr,
  warnings: z.array(str).default([]),
  message: optStr,
});
export type Answer = z.infer<typeof Answer>;

export const Duplicates = z.array(
  z.object({ score: z.number(), a: z.object({ id: str, title: str }), b: z.object({ id: str, title: str }) }),
);

export const Digest = z.object({
  days: z.number().optional(),
  total: z.number().optional(),
  items: z.array(z.object({ id: str, title: str, kind: str, provenance: optStr, created_at: str })).default([]),
  resurfaced: z.array(z.object({ id: str, title: str, created_at: optStr }).loose()).default([]),
});

export const Submitted = z.object({ id: str, status: optStr, duplicate: z.boolean().optional() }).loose();
export const Ok = z.object({ ok: z.boolean() }).loose();

export const Privacy = z.object({
  allow_remote: z.boolean(),
  backends: z.array(z.object({ name: str, locality: optStr, type: optStr })),
  skipped: z.array(z.unknown()).default([]),
  egress: z
    .object({
      routes: z.record(
        str,
        z.object({ remote: z.array(str).default([]), local: z.array(str).default([]), blocked: z.boolean().default(false) }),
      ),
    })
    .partial()
    .optional(),
});

export const Config = z.object({
  path: str,
  allow_remote: z.boolean(),
  backends: z.record(str, z.object({ spec: z.record(str, z.unknown()), editable: z.boolean() })),
  tasks: z.record(str, z.array(str)),
  types: z.record(str, z.array(str)),
  task_names: z.array(str),
  presets: z.record(str, z.record(str, z.unknown())),
  subscriptions: z.array(str).default([]),
});
export type Config = z.infer<typeof Config>;

export const Providers = z.object({ providers: z.array(z.unknown()) });
export const Models = z.object({ models: z.array(str) });

export const Shelf = z.object({
  id: str,
  name: str,
  blurb: z.string().default(""),
  todo: z.boolean().default(false),
  done_label: optStr,
  builtin: z.boolean().default(false),
  position: z.number().default(0),
  count: z.number().default(0),
  todo_count: z.number().default(0),
});
export type Shelf = z.infer<typeof Shelf>;
export const Shelves = z.object({ shelves: z.array(Shelf) });

export const Resurfaced = z.object({
  items: z.array(z.object({ id: str, title: str, why: str, kind: str, shelf: str, score: z.number() }).loose()),
});
export type Resurfaced = z.infer<typeof Resurfaced>;

export const EntryRows = z.object({
  entries: z.array(Entry.extend({ note: z.object({ id: str, title: str, shelf: str }) })),
});
