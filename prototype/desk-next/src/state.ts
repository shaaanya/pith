import { useEffect, useState } from "react";
import { makeDataset, type Dataset, type Group, type Workspace } from "./data";
export const STORAGE_KEY = "pith.prototype.desk-next.v1";
export type DeskState = {
  version: 1;
  dataset: Dataset;
  groups: Group[];
  focused: string[];
  workspace: Workspace;
  expanded: Record<Workspace, string[]>;
  theme: "light" | "dark";
};
export function fresh(dataset: Dataset = "rich"): DeskState {
  return {
    version: 1,
    dataset,
    groups: makeDataset(dataset).groups,
    focused: [],
    workspace: "overview",
    expanded: { overview: [], focus: [] },
    theme: window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light",
  };
}
function load(): DeskState {
  try {
    const s = JSON.parse(
      localStorage.getItem(STORAGE_KEY) ?? "null",
    ) as DeskState | null;
    if (
      s?.version !== 1 ||
      !["empty", "sparse", "rich"].includes(s.dataset) ||
      !Array.isArray(s.groups) ||
      !Array.isArray(s.focused) ||
      !["focus", "overview"].includes(s.workspace) ||
      !["light", "dark"].includes(s.theme) ||
      !Array.isArray(s.expanded?.focus) ||
      !Array.isArray(s.expanded?.overview)
    )
      return fresh();
    const items = new Set(makeDataset(s.dataset).items.map((i) => i.id));
    const ids = new Set<string>();
    for (const g of s.groups) {
      if (
        !g ||
        typeof g.id !== "string" ||
        ids.has(g.id) ||
        typeof g.title !== "string" ||
        !g.title.trim() ||
        typeof g.description !== "string" ||
        typeof g.icon !== "string" ||
        !Array.isArray(g.itemIds) ||
        g.itemIds.some((i) => typeof i !== "string")
      )
        return fresh();
      ids.add(g.id);
      g.itemIds = [...new Set(g.itemIds)].filter((i) => items.has(i));
    }
    s.focused = [...new Set(s.focused)].filter((i) => ids.has(i));
    for (const w of ["overview", "focus"] as const)
      s.expanded[w] = [...new Set(s.expanded[w])].filter((i) => ids.has(i));
    return s;
  } catch {
    return fresh();
  }
}
export function useDesk() {
  const [state, setState] = useState(load);
  const [storageUnavailable, setStorageUnavailable] = useState(false);
  useEffect(() => {
    document.documentElement.dataset.theme = state.theme;
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
      setStorageUnavailable(false);
    } catch {
      setStorageUnavailable(true);
    }
  }, [state]);
  return { state, setState, storageUnavailable };
}
