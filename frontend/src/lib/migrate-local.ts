/**
 * One-shot import of the state older versions kept only in this browser (`pith.mind.v1`): moves, done
 * marks, snoozes, hides, ticked entries, custom shelves, recently opened. Everything goes through the
 * public API, then the key is removed. A network failure leaves the key so the next load tries again;
 * a note that no longer exists (404) is skipped.
 */
import { z } from "zod";
import { ApiError, request } from "./api";
import { remove, read } from "./local";
import { layout } from "./shelves";
import * as S from "./schemas";

const KEY = "pith.mind.v1";

type Old = {
  notes?: Record<string, { shelf?: string; done?: string; snooze?: string; hide?: boolean }>;
  entries?: Record<string, string>;
  opened?: string[];
  shelves?: { id: string; name: string; blurb?: string }[];
  hidden?: string[];
  collapsed?: boolean;
};

/** The hash older versions keyed entries by (djb2 over the normalised text). */
export function hashText(t: string): string {
  const s = t.toLowerCase().replace(/\s+/g, " ").trim();
  let h = 5381;
  for (let i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) | 0;
  return (h >>> 0).toString(36);
}

export async function migrateLocal(): Promise<void> {
  const raw = read(KEY);
  if (!raw) return;
  let old: Old;
  try {
    old = JSON.parse(raw) as Old;
  } catch {
    remove(KEY);
    return;
  }
  for (const id of old.hidden ?? []) layout.hide(id);
  if (old.collapsed) layout.collapse(true);

  let failed = false;
  /** Run one call; a 4xx means "gone or invalid, skip it", anything else keeps the key for a retry. */
  const attempt = async <T>(f: () => Promise<T>): Promise<T | null> => {
    try {
      return await f();
    } catch (e) {
      if (!(e instanceof ApiError && e.status >= 400 && e.status < 500)) failed = true;
      return null;
    }
  };

  const shelfIds = new Map<string, string>(); // local custom id -> server id
  for (const s of old.shelves ?? []) {
    const made = await attempt(() => request(S.Shelf, "POST", "/api/shelves", { name: s.name, blurb: s.blurb ?? "" }));
    if (made) shelfIds.set(s.id, made.id);
    else {
      const all = await attempt(() => request(S.Shelves, "GET", "/api/shelves"));
      const hit = all?.shelves.find((x) => x.name.toLowerCase() === s.name.toLowerCase());
      if (hit) shelfIds.set(s.id, hit.id);
    }
  }

  const future = (iso?: string) => !!iso && Date.parse(iso) > Date.now();
  for (const [id, n] of Object.entries(old.notes ?? {})) {
    const body: Record<string, unknown> = {};
    const shelf = n.shelf ? (shelfIds.get(n.shelf) ?? (n.shelf.startsWith("u-") ? undefined : n.shelf)) : undefined;
    if (shelf) body.shelf = shelf;
    if (n.done) body.done = true;
    if (future(n.snooze)) body.snooze_until = n.snooze;
    if (n.hide) body.hidden = true;
    if (Object.keys(body).length) await attempt(() => request(z.unknown(), "PATCH", `/api/items/${id}`, body));
  }

  const byNote = new Map<string, Set<string>>();
  for (const key of Object.keys(old.entries ?? {})) {
    const [id, h] = key.split("|");
    if (id && h) byNote.set(id, (byNote.get(id) ?? new Set()).add(h));
  }
  const Detail = z.object({ entries: z.array(S.Entry).default([]) }).loose();
  for (const [id, hashes] of byNote) {
    const d = await attempt(() => request(Detail, "GET", `/api/items/${id}`));
    for (const e of d?.entries ?? [])
      if (hashes.has(hashText(e.text))) await attempt(() => request(z.unknown(), "PATCH", `/api/entries/${e.id}`, { done: true }));
  }

  for (const id of [...(old.opened ?? [])].reverse()) await attempt(() => request(z.unknown(), "POST", `/api/items/${id}/viewed`, {}));

  if (!failed) remove(KEY);
}
