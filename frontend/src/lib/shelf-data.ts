import { useMemo } from "react";
import { useNotesIndex, useShelves } from "./queries";
import { BUILTIN, orderShelves, toPlaced, toShelfDef, usePrefs, type Placed, type ShelfDef } from "./shelves";

export type ShelfData = {
  ready: boolean;
  /** More notes exist than the browser index holds (3,000 cap). */
  truncated: boolean;
  total: number;
  placed: Placed[];
  shelves: ShelfDef[];
  /** shelf id -> notes on it, newest first. */
  byShelf: Map<string, Placed[]>;
  /** Notes on to-do shelves not marked done. */
  open: Placed[];
  todo: Set<string>;
  byId: Map<string, Placed>;
};

/** The one place notes meet shelves. Shelf, placement and done state come from the backend. */
export function useShelfData(): ShelfData {
  const idx = useNotesIndex();
  const srv = useShelves();
  const { hidden } = usePrefs();
  return useMemo(() => {
    const all = srv.data ? srv.data.shelves.map(toShelfDef) : BUILTIN;
    const shelves = orderShelves(all, hidden);
    const known = new Set(shelves.map((s) => s.id));
    const todo = new Set(shelves.filter((s) => s.todo).map((s) => s.id));
    const placed = (idx.data?.items ?? []).map((item) => {
      const p = toPlaced(item);
      // A hidden shelf is not a destination (unless you put the note there): show it on Reference/Other.
      if (!known.has(p.placement.shelf) && p.placement.by !== "you")
        return { ...p, placement: { ...p.placement, shelf: item.topics.length ? "reference" : "other" } };
      return p;
    });
    const byShelf = new Map<string, Placed[]>(shelves.map((s) => [s.id, []]));
    for (const p of placed) (byShelf.get(p.placement.shelf) ?? byShelf.get("other"))?.push(p);
    return {
      ready: !!idx.data,
      truncated: !!idx.data?.truncated,
      total: idx.data?.total ?? 0,
      placed,
      shelves,
      byShelf,
      open: placed.filter((p) => todo.has(p.placement.shelf) && !p.state.done),
      todo,
      byId: new Map(placed.map((p) => [p.item.id, p])),
    };
  }, [idx.data, srv.data, hidden]);
}
