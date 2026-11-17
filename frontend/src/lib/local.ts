/** Per-browser conveniences. Every access is guarded: storage can be blocked or throw. */
export function read(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}
export function write(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* storage unavailable: the app works without it */
  }
}

/**
 * "Since you were last here": the stamp is fixed for the whole browser session so the Today and
 * Inbox pages agree on what is new, then advanced for the next visit.
 */
export const lastVisit: string | null = (() => {
  let prev: string | null = null;
  try {
    prev = sessionStorage.getItem("pith.prevVisit");
  } catch {
    /* ignore */
  }
  if (prev === null) {
    prev = read("pith.lastVisit");
    try {
      sessionStorage.setItem("pith.prevVisit", prev ?? "");
    } catch {
      /* ignore */
    }
  }
  write("pith.lastVisit", new Date().toISOString());
  return prev || null;
})();

export const isNew = (iso: string | null | undefined) => !!iso && !!lastVisit && iso > lastVisit;

export type Theme = "system" | "light" | "dark";
export function applyTheme(t: Theme) {
  const el = document.documentElement;
  if (t === "system") el.removeAttribute("data-theme");
  else el.setAttribute("data-theme", t);
}
export const getTheme = (): Theme => {
  const v = read("pith.theme");
  return v === "light" || v === "dark" ? v : "system";
};
export function setTheme(t: Theme) {
  write("pith.theme", t);
  applyTheme(t);
}
