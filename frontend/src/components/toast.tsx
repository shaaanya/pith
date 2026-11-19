import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { cn } from "@/lib/utils";

type Toast = { id: number; text: string; bad?: boolean };
const Ctx = createContext<(text: string, opts?: { bad?: boolean }) => void>(() => undefined);
export const useToast = () => useContext(Ctx);

/** Minimal live-region toasts. No third-party toast library: they inject un-nonced <style> tags. */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const seq = useRef(0);
  const push = useCallback((text: string, opts?: { bad?: boolean }) => {
    const id = ++seq.current;
    setToasts((t) => [...t.slice(-3), { id, text, bad: opts?.bad }]);
    window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), opts?.bad ? 7000 : 3800);
  }, []);
  const value = useMemo(() => push, [push]);
  // non-React code (the note actions in lib/shelves) reports failures with a window event
  useEffect(() => {
    const on = (e: Event) => push(String((e as CustomEvent).detail || "That did not save."), { bad: true });
    window.addEventListener("pith:error", on);
    return () => window.removeEventListener("pith:error", on);
  }, [push]);
  return (
    <Ctx.Provider value={value}>
      {children}
      <div
        role="status"
        aria-live="polite"
        className="pointer-events-none fixed inset-x-0 bottom-[calc(4.5rem+env(safe-area-inset-bottom))] z-[60] flex flex-col items-center gap-2 px-4 md:bottom-6"
      >
        {toasts.map((t) => (
          <div
            key={t.id}
            className={cn(
              "enter pointer-events-auto max-w-md rounded-lg border px-3.5 py-2 text-[13.5px] shadow-xl",
              t.bad ? "border-bad/50 bg-bad-tint text-bad" : "border-line bg-raise text-ink",
            )}
          >
            {t.text}
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}
