/**
 * Shelves: what a note is *useful for* (topics say what it is *about*).
 *
 * Shelf, placement, done / snooze / hidden state and entries all live in the backend (they are in
 * `pith backup` and shared between devices). Placement is made by the backend: the model reads the note
 * and your reason, rules are the fallback, and your own move always wins. Content type is not a signal:
 * a saved reel is already distilled, so "video" says nothing about what it is for.
 *
 * What stays in this browser is only layout: which built-in shelves you hid and whether the sidebar
 * section is collapsed.
 */
import { useSyncExternalStore } from "react";
import { z } from "zod";
import { request } from "./api";
import { queryClient } from "./client";
import { read, write } from "./local";
import * as S from "./schemas";
import type { LibraryItem } from "./schemas";

export type ShelfDef = {
  id: string;
  name: string;
  /** One line: what belongs here. */
  blurb: string;
  /** Has a to-do / done state (things you intend to act on). */
  todo: boolean;
  builtin: boolean;
  /** Verb used for the done mark: "Watched", "Read" … */
  doneLabel?: string;
};

/** Built-in shelves: names for the icon set and hide list, and the shape shown before the API answers. */
export const BUILTIN: ShelfDef[] = [
  { id: "watch", name: "Watch", blurb: "Films, shows and videos you meant to see", todo: true, builtin: true, doneLabel: "Watched" },
  { id: "listen", name: "Listen", blurb: "Music, podcasts and talks", todo: true, builtin: true, doneLabel: "Listened" },
  { id: "read", name: "Read", blurb: "Books, essays and long reads", todo: true, builtin: true, doneLabel: "Read" },
  { id: "play", name: "Play", blurb: "Games to play", todo: true, builtin: true, doneLabel: "Played" },
  { id: "try", name: "Try", blurb: "Tools, repos and apps to try out", todo: true, builtin: true, doneLabel: "Tried" },
  { id: "visit", name: "Visit", blurb: "Places to go", todo: true, builtin: true, doneLabel: "Visited" },
  { id: "reference", name: "Reference", blurb: "Knowledge to keep and look up", todo: false, builtin: true },
  { id: "other", name: "Other", blurb: "Not sure yet: needs a home", todo: false, builtin: true },
];

export type Placement = {
  shelf: string;
  /** Who decided: you, the model, your reason, the site, or the fallback. */
  by: "you" | "model" | "reason" | "site" | "default" | "none";
  /** Plain-language explanation shown next to the placement. */
  why: string;
};

export type NoteState = {
  /** ISO time it was marked done. */
  done?: string;
  /** Hidden from Worth revisiting until this ISO time. */
  snooze?: string;
  /** Never resurface. */
  hide?: boolean;
};

export type Placed = { item: LibraryItem; placement: Placement; state: NoteState };

export const toShelfDef = (s: S.Shelf): ShelfDef => ({
  id: s.id,
  name: s.name,
  blurb: s.blurb,
  todo: s.todo,
  builtin: s.builtin,
  doneLabel: s.done_label ?? (s.todo ? "Done" : undefined),
});

export const toPlaced = (item: LibraryItem): Placed => ({
  item,
  placement: { shelf: item.shelf, by: item.placement.by, why: item.placement.why },
  state: {
    done: item.state.done_at ?? undefined,
    snooze: item.state.snooze_until ?? undefined,
    hide: item.state.hidden || undefined,
  },
});

/** Visible shelves in sidebar order: built-ins, your own, then Other. Hidden built-ins are left out. */
export function orderShelves(all: ShelfDef[], hidden: string[]): ShelfDef[] {
  const shown = all.filter((s) => !hidden.includes(s.id) || s.id === "other");
  return [...shown.filter((s) => s.id !== "other" && s.builtin), ...shown.filter((s) => !s.builtin), ...shown.filter((s) => s.id === "other")];
}

export const shelfById = (shelves: ShelfDef[], id: string): ShelfDef | undefined =>
  shelves.find((s) => s.id === id) ?? BUILTIN.find((s) => s.id === id);

// ---- this browser's layout preferences -------------------------------------------------------------

type Prefs = { hidden: string[]; collapsed: boolean; rail: boolean };
const KEY = "pith.prefs.v1";
const EMPTY: Prefs = { hidden: [], collapsed: false, rail: false };

function load(): Prefs {
  const raw = read(KEY);
  if (!raw) return EMPTY;
  try {
    return { ...EMPTY, ...(JSON.parse(raw) as Partial<Prefs>) };
  } catch {
    return EMPTY;
  }
}

let prefs: Prefs = load();
const listeners = new Set<() => void>();
const commit = (next: Prefs) => {
  prefs = next;
  write(KEY, JSON.stringify(next));
  listeners.forEach((l) => l());
};
if (typeof window !== "undefined")
  window.addEventListener("storage", (e) => {
    if (e.key === KEY) {
      prefs = load();
      listeners.forEach((l) => l());
    }
  });
const subscribe = (l: () => void) => (listeners.add(l), () => void listeners.delete(l));
export const usePrefs = () =>
  useSyncExternalStore(
    subscribe,
    () => prefs,
    () => EMPTY,
  );
export const layout = {
  toggleHidden: (id: string) => commit({ ...prefs, hidden: prefs.hidden.includes(id) ? prefs.hidden.filter((x) => x !== id) : [...prefs.hidden, id] }),
  hide: (id: string) => (prefs.hidden.includes(id) ? undefined : commit({ ...prefs, hidden: [...prefs.hidden, id] })),
  collapse: (c: boolean) => commit({ ...prefs, collapsed: c }),
  rail: (r: boolean) => commit({ ...prefs, rail: r }),
};

// ---- what you do to notes: saved by the backend ---------------------------------------------------

type Index = { items: LibraryItem[]; total: number; truncated: boolean };
const INDEX_KEY = ["library", "index"] as const;
const patchIndex = (id: string, f: (i: LibraryItem) => LibraryItem) =>
  queryClient.setQueryData<Index>(INDEX_KEY, (d) => d && { ...d, items: d.items.map((i) => (i.id === id ? f(i) : i)) });

/** Refetch what an action changed. The big note index is patched in place instead (a tick must not re-download it). */
const refresh = (index: boolean) => {
  for (const k of ["library", "shelves", "entries", "resurface", "item"])
    void queryClient.invalidateQueries({
      queryKey: [k],
      predicate: (q) => index || !(q.queryKey[0] === "library" && q.queryKey[1] === "index"),
    });
};
/** Send a change. On failure the screen is rolled back to the server's truth and the person is told. */
const send = (method: "POST" | "PATCH" | "DELETE", path: string, body?: unknown, index = false) =>
  request(z.unknown(), method, path, body).then(
    () => refresh(index),
    (e: unknown) => {
      refresh(true);
      window.dispatchEvent(new CustomEvent("pith:error", { detail: e instanceof Error ? e.message : "That did not save." }));
    },
  );

const patchState = (id: string, p: Partial<LibraryItem["state"]>) => patchIndex(id, (i) => ({ ...i, state: { ...i.state, ...p } }));

export const mind = {
  /** Move a note to a shelf; undefined lets Pith decide again. */
  move: (id: string, shelf: string | undefined) => {
    if (shelf) patchIndex(id, (i) => ({ ...i, shelf, placement: { by: "you", why: "You put it here" } }));
    void send("PATCH", `/api/items/${id}`, { shelf: shelf ?? null }, shelf === undefined);
  },
  setDone: (id: string, done: boolean) => {
    patchState(id, { done_at: done ? new Date().toISOString() : null });
    void send("PATCH", `/api/items/${id}`, { done });
  },
  snooze: (id: string, days: number) => {
    const until = new Date(Date.now() + days * 86_400_000).toISOString();
    patchState(id, { snooze_until: until });
    void send("PATCH", `/api/items/${id}`, { snooze_until: until });
  },
  hide: (id: string) => {
    patchState(id, { hidden: true });
    void send("PATCH", `/api/items/${id}`, { hidden: true });
  },
  entry: (entryId: string, done: boolean) => void send("PATCH", `/api/entries/${entryId}`, { done }),
  opened: (id: string) =>
    void request(z.unknown(), "POST", `/api/items/${id}/viewed`, {}).then(() =>
      queryClient.invalidateQueries({ queryKey: ["library", "viewed"] }),
    ),
  addShelf: (name: string, blurb: string) => void send("POST", "/api/shelves", { name: name.trim(), blurb: blurb.trim() }, true),
  removeShelf: (id: string) => void send("DELETE", `/api/shelves/${id}`, undefined, true),
};
