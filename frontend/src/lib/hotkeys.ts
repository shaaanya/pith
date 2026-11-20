import { useEffect, useRef } from "react";

const typing = (t: EventTarget | null) => {
  const el = t as HTMLElement | null;
  if (!el) return false;
  return el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName);
};

export type Keymap = Record<string, (e: KeyboardEvent) => void>;

/**
 * Global shortcuts. Keys: "n", "/", "?", "mod+k" and two-key sequences "g t". Ignored while typing
 * (except mod+ combos and Escape) and while a dialog is open (Radix marks the trigger inert).
 */
export function useHotkeys(map: Keymap, enabled = true) {
  const ref = useRef(map);
  ref.current = map;
  useEffect(() => {
    if (!enabled) return;
    let pending: string | null = null;
    let timer: number | undefined;
    const onKey = (e: KeyboardEvent) => {
      // Native modal owns Escape and makes the page inert, including its shortcuts.
      if (document.querySelector("dialog[open]")) return;
      const mod = e.metaKey || e.ctrlKey;
      const k = e.key.length === 1 ? e.key.toLowerCase() : e.key;
      if (e.altKey) return;
      const isTyping = typing(e.target);
      const dialogOpen = !!document.querySelector('[role="dialog"]');
      if (mod) {
        ref.current[`mod+${k}`]?.(e);
        return;
      }
      if (k === "Escape") {
        ref.current["Escape"]?.(e);
        return;
      }
      if (isTyping || dialogOpen) return;
      if (pending) {
        const combo = `${pending} ${k}`;
        pending = null;
        window.clearTimeout(timer);
        if (ref.current[combo]) {
          e.preventDefault();
          ref.current[combo]?.(e);
          return;
        }
      }
      if (k === "g") {
        pending = "g";
        timer = window.setTimeout(() => (pending = null), 900);
        return;
      }
      const fn = ref.current[k];
      if (fn) {
        fn(e);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.clearTimeout(timer);
    };
  }, [enabled]);
}
