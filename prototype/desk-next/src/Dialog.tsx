import { useEffect, useRef, type ReactNode } from "react";
import { X } from "lucide-react";

/** Native modality owns inertness, tab containment and Escape. No second trap. */
export function Dialog({
  title,
  onClose,
  children,
  wide = false,
  opener,
  restoreFocus,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
  opener: HTMLElement | null;
  restoreFocus?: () => HTMLElement | null;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const outside = useRef(false);
  const scroll = useRef(window.scrollY);
  useEffect(() => {
    const dialog = ref.current!;
    dialog.showModal();
    const initial =
      dialog.querySelector<HTMLElement>("[data-initial-focus]") ??
      dialog.querySelector<HTMLElement>("h2");
    initial?.focus({ preventScroll: true });
    // Firefox/WebKit can chain scroll from a modal to the document. Keep the
    // root scrollbar/layout intact; stop only gestures that cannot scroll here.
    const scrollers = (target: EventTarget | null) => {
      const result: HTMLElement[] = [];
      let node = target instanceof Element ? target : null;
      while (node && node !== dialog) {
        if (
          node instanceof HTMLElement &&
          /auto|scroll/.test(getComputedStyle(node).overflowY)
        )
          result.push(node);
        node = node.parentElement;
      }
      return result;
    };
    const canScroll = (el: HTMLElement | null, delta: number) =>
      !!el &&
      (delta < 0
        ? el.scrollTop > 0
        : el.scrollTop + el.clientHeight < el.scrollHeight - 1);
    const wheel = (e: WheelEvent) => {
      if (e.ctrlKey || Math.abs(e.deltaX) > Math.abs(e.deltaY)) return;
      if (!scrollers(e.target).some((el) => canScroll(el, e.deltaY)))
        e.preventDefault();
    };
    let touchY = 0,
      touchX = 0;
    const touchStart = (e: TouchEvent) => {
      touchY = e.touches[0]?.clientY ?? 0;
      touchX = e.touches[0]?.clientX ?? 0;
    };
    const touchMove = (e: TouchEvent) => {
      if (e.touches.length !== 1) return;
      const next = e.touches[0].clientY,
        nextX = e.touches[0].clientX,
        delta = touchY - next,
        deltaX = touchX - nextX;
      touchY = next;
      touchX = nextX;
      if (Math.abs(deltaX) > Math.abs(delta)) return;
      if (!scrollers(e.target).some((el) => canScroll(el, delta)))
        e.preventDefault();
    };
    const readingKey = (e: KeyboardEvent) => {
      if (
        e.altKey ||
        e.metaKey ||
        e.ctrlKey ||
        !(e.target instanceof Element) ||
        e.target.closest("input,textarea,select,[contenteditable]")
      )
        return;
      if (e.key === " " && e.target.closest("button,a,summary")) return;
      const direction =
        ["ArrowUp", "PageUp", "Home"].includes(e.key) ||
        (e.key === " " && e.shiftKey)
          ? -1
          : 1;
      const containers = scrollers(e.target);
      const body =
        containers.find((el) => canScroll(el, direction)) ??
        containers[0] ??
        dialog.querySelector<HTMLElement>(".modal-body");
      if (!body) return;
      const page = Math.max(40, body.clientHeight * 0.85);
      const delta: Record<string, number> = {
        ArrowDown: 40,
        ArrowUp: -40,
        PageDown: page,
        PageUp: -page,
        " ": e.shiftKey ? -page : page,
        Home: -body.scrollHeight,
        End: body.scrollHeight,
      };
      if (!(e.key in delta)) return;
      e.preventDefault();
      body.scrollBy({ top: delta[e.key], behavior: "instant" });
    };
    dialog.addEventListener("wheel", wheel, { passive: false });
    dialog.addEventListener("touchstart", touchStart, { passive: true });
    dialog.addEventListener("touchmove", touchMove, { passive: false });
    dialog.addEventListener("keydown", readingKey);
    return () => {
      dialog.removeEventListener("wheel", wheel);
      dialog.removeEventListener("touchstart", touchStart);
      dialog.removeEventListener("touchmove", touchMove);
      dialog.removeEventListener("keydown", readingKey);
      if (dialog.open) dialog.close();
    };
  }, []);
  useEffect(() => {
    if (ref.current?.open)
      (
        ref.current.querySelector<HTMLElement>("[data-initial-focus]") ??
        ref.current.querySelector<HTMLElement>("h2")
      )?.focus({ preventScroll: true });
  }, [title]);
  const close = () => ref.current?.close();
  const isOutside = (x: number, y: number) => {
    const r = ref.current!.getBoundingClientRect();
    return x < r.left || x > r.right || y < r.top || y > r.bottom;
  };
  return (
    <dialog
      ref={ref}
      className={wide ? "modal reader-modal" : "modal"}
      aria-labelledby="dialog-title"
      onPointerDown={(e) => {
        outside.current = isOutside(e.clientX, e.clientY);
      }}
      onPointerUp={(e) => {
        if (outside.current && isOutside(e.clientX, e.clientY)) close();
        outside.current = false;
      }}
      onClose={() => {
        window.scrollTo({ top: scroll.current, behavior: "instant" });
        onClose();
        // Native return handles ordinary invokers; explicit identity also covers related-item navigation.
        requestAnimationFrame(() => {
          if (document.querySelector("dialog[open]")) return;
          (
            restoreFocus?.() ??
            (opener?.isConnected
              ? opener
              : document.getElementById("page-title"))
          )?.focus({ preventScroll: true });
        });
      }}
    >
      <header className="modal-header">
        <h2 id="dialog-title" tabIndex={-1}>
          {title}
        </h2>
        <button
          type="button"
          className="icon-button"
          onClick={close}
          aria-label="Close"
        >
          <X size={20} />
        </button>
      </header>
      {children}
    </dialog>
  );
}
