import { useEffect, useId, useRef, type ReactNode } from "react";
import { X } from "lucide-react";

/** Native modality owns inertness, focus containment and Escape. */
export function DeskDialog({
  title,
  onClose,
  opener,
  wide = false,
  children,
}: {
  title: string;
  onClose: () => void;
  opener?: HTMLElement | null;
  wide?: boolean;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const callbacks = useRef({ onClose, opener });
  callbacks.current = { onClose, opener };
  const outside = useRef(false);
  useEffect(() => {
    const dialog = ref.current!;
    const scroll = window.scrollY;
    const invoker = callbacks.current.opener ?? (document.activeElement instanceof HTMLElement ? document.activeElement : null);
    const groupId = invoker?.closest<HTMLElement>("[data-group-id]")?.dataset.groupId;
    let restored = false;
    const restore = () => {
      if (restored) return;
      restored = true;
      requestAnimationFrame(() => {
        // A successor dialog owns focus; nested confirms return to the parent reader.
        const activeDialog = document.querySelector("dialog[open]");
        if (activeDialog && (!invoker || !activeDialog.contains(invoker))) return;
        window.scrollTo({ top: scroll, behavior: "instant" });
        const target = invoker?.isConnected
          ? invoker
          : ((groupId ? document.getElementById(`trigger-${groupId}`) : null) ??
            document.getElementById("page-title") ??
            document.getElementById("main"));
        target?.focus({ preventScroll: true });
      });
    };
    dialog.showModal();
    (dialog.querySelector<HTMLElement>("[data-initial-focus]") ?? dialog.querySelector<HTMLElement>("h2"))?.focus({ preventScroll: true });
    // Some engines still chain gestures from a non-scrollable dialog to the document.
    const scrollers = (target: EventTarget | null) => {
      const result: HTMLElement[] = [];
      let node = target instanceof Element ? target : null;
      while (node && node !== dialog) {
        if (node instanceof HTMLElement && /auto|scroll/.test(getComputedStyle(node).overflowY)) result.push(node);
        node = node.parentElement;
      }
      return result;
    };
    const canScroll = (el: HTMLElement, delta: number) =>
      delta < 0 ? el.scrollTop > 0 : el.scrollTop + el.clientHeight < el.scrollHeight - 1;
    const wheel = (event: WheelEvent) => {
      if (
        !event.ctrlKey &&
        Math.abs(event.deltaY) >= Math.abs(event.deltaX) &&
        !scrollers(event.target).some((el) => canScroll(el, event.deltaY))
      )
        event.preventDefault();
    };
    let touchY = 0;
    let touchX = 0;
    const touchStart = (event: TouchEvent) => {
      touchY = event.touches[0]?.clientY ?? 0;
      touchX = event.touches[0]?.clientX ?? 0;
    };
    const touchMove = (event: TouchEvent) => {
      if (event.touches.length !== 1) return;
      const point = event.touches[0];
      if (!point) return;
      const delta = touchY - point.clientY;
      const horizontal = touchX - point.clientX;
      touchY = point.clientY;
      touchX = point.clientX;
      if (Math.abs(delta) >= Math.abs(horizontal) && !scrollers(event.target).some((el) => canScroll(el, delta))) event.preventDefault();
    };
    const readingKey = (event: KeyboardEvent) => {
      if (
        event.altKey ||
        event.metaKey ||
        event.ctrlKey ||
        !(event.target instanceof Element) ||
        event.target.closest("input,textarea,select,[contenteditable]")
      )
        return;
      if (event.key === " " && event.target.closest("button,a,summary")) return;
      const containers = scrollers(event.target);
      const direction = ["ArrowUp", "PageUp", "Home"].includes(event.key) || (event.key === " " && event.shiftKey) ? -1 : 1;
      const body =
        containers.find((el) => canScroll(el, direction)) ??
        containers[0] ??
        dialog.querySelector<HTMLElement>(".v5-dialog-body, .desk-reader-body");
      if (!body) return;
      const page = Math.max(40, body.clientHeight * 0.85);
      const deltas: Record<string, number> = {
        ArrowDown: 40,
        ArrowUp: -40,
        PageDown: page,
        PageUp: -page,
        " ": event.shiftKey ? -page : page,
        Home: -body.scrollHeight,
        End: body.scrollHeight,
      };
      const delta = deltas[event.key];
      if (delta === undefined) return;
      event.preventDefault();
      body.scrollBy({ top: delta, behavior: "instant" });
    };
    const close = () => {
      callbacks.current.onClose();
      restore();
    };
    dialog.addEventListener("wheel", wheel, { passive: false });
    dialog.addEventListener("touchstart", touchStart, { passive: true });
    dialog.addEventListener("touchmove", touchMove, { passive: false });
    dialog.addEventListener("close", close);
    dialog.addEventListener("keydown", readingKey);
    return () => {
      dialog.removeEventListener("wheel", wheel);
      dialog.removeEventListener("touchstart", touchStart);
      dialog.removeEventListener("touchmove", touchMove);
      dialog.removeEventListener("close", close);
      dialog.removeEventListener("keydown", readingKey);
      if (dialog.open) dialog.close();
      restore();
    };
  }, []);
  useEffect(() => {
    const frame = requestAnimationFrame(() => {
      const dialog = ref.current;
      if (dialog?.open)
        (dialog.querySelector<HTMLElement>("[data-initial-focus]") ?? dialog.querySelector<HTMLElement>("h2"))?.focus({
          preventScroll: true,
        });
    });
    return () => cancelAnimationFrame(frame);
  }, [title]);
  const isOutside = (x: number, y: number) => {
    const rect = ref.current!.getBoundingClientRect();
    return x < rect.left || x > rect.right || y < rect.top || y > rect.bottom;
  };
  return (
    <dialog
      ref={ref}
      className={`v5-dialog${wide ? " v5-reader-dialog" : ""}`}
      aria-labelledby={titleId}
      onPointerDown={(event) => {
        outside.current = isOutside(event.clientX, event.clientY);
      }}
      onPointerUp={(event) => {
        if (outside.current && isOutside(event.clientX, event.clientY)) ref.current?.close();
        outside.current = false;
      }}
    >
      <header className="v5-dialog-header">
        <h2 id={titleId} tabIndex={-1}>
          {title}
        </h2>
        <button type="button" className="v5-icon-button" onClick={() => ref.current?.close()} aria-label="Close">
          <X size={20} aria-hidden />
        </button>
      </header>
      {children}
    </dialog>
  );
}
