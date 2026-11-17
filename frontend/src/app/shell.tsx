import { BookOpen, Inbox, LayoutDashboard, Plus, Search, Settings, Keyboard } from "lucide-react";
import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate, useRouteError } from "react-router";
import { Modal, TooltipProvider } from "@/components/overlay";
import { Button, EmptyState, Kbd } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { useHotkeys } from "@/lib/hotkeys";
import { useAppState } from "@/lib/queries";
import { cn } from "@/lib/utils";
import { CaptureProvider, useCapture } from "./capture";

const NAV = [
  { to: "/", label: "Today", icon: LayoutDashboard, end: true, key: "t" },
  { to: "/inbox", label: "Inbox", icon: Inbox, key: "i" },
  { to: "/library", label: "Library", icon: BookOpen, key: "l" },
  { to: "/search", label: "Search & Ask", short: "Search", icon: Search, key: "s" },
  { to: "/settings", label: "Settings", icon: Settings, key: "," },
] as const;

const SHORTCUTS: [string, string][] = [
  ["n", "Save a link, text or file"],
  ["/  or  ⌘K", "Search and ask"],
  ["g t / g i / g l / g s", "Go to Today, Inbox, Library, Search"],
  ["g ,", "Open Settings"],
  ["j / k", "Next / previous in a list"],
  ["Enter", "Open the selected note"],
  ["x", "Select the focused row (Library)"],
  ["e", "Edit the open note"],
  ["c", "Copy the open note as Markdown"],
  ["Esc", "Back / close"],
  ["?", "Show this list"],
];

export function Shell() {
  return (
    <TooltipProvider>
      <CaptureProvider>
        <Frame />
      </CaptureProvider>
    </TooltipProvider>
  );
}

function Frame() {
  const nav = useNavigate();
  const loc = useLocation();
  const { open } = useCapture();
  const [help, setHelp] = useState(false);
  const state = useAppState();
  const attention = (state.data?.counts.failed ?? 0) + (state.data?.counts.needs_clarification ?? 0);
  const working = (state.data?.counts.pending ?? 0) + (state.data?.counts.processing ?? 0) + (state.data?.counts.new ?? 0);

  useHotkeys({
    n: (e) => (e.preventDefault(), open()),
    "/": (e) => (e.preventDefault(), nav("/search?focus=1")),
    "mod+k": (e) => (e.preventDefault(), nav("/search?focus=1")),
    "?": () => setHelp(true),
    "g t": () => nav("/"),
    "g i": () => nav("/inbox"),
    "g l": () => nav("/library"),
    "g s": () => nav("/search?focus=1"),
    "g ,": () => nav("/settings"),
  });

  // Move focus to the page on navigation so keyboard and screen-reader users start at the content.
  useEffect(() => {
    const main = document.getElementById("main");
    if (main && !main.contains(document.activeElement)) main.focus({ preventScroll: true });
  }, [loc.pathname]);

  return (
    <div className="min-h-dvh md:grid md:grid-cols-[13.5rem_minmax(0,1fr)]">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-[80] focus:rounded-md focus:bg-acc focus:px-3 focus:py-1.5 focus:text-acc-ink"
      >
        Skip to content
      </a>

      {/* Desktop rail */}
      <aside className="sticky top-0 hidden h-dvh flex-col border-r border-hair bg-panel/60 px-3 py-4 md:flex" aria-label="Primary">
        <div className="px-2 pb-4 font-serif text-[22px] font-semibold tracking-tight">Pith</div>
        <Button variant="primary" className="mb-4 w-full justify-start" onClick={open}>
          <Plus className="size-4" aria-hidden /> Save something
          <span className="ml-auto opacity-70">
            <Kbd>n</Kbd>
          </span>
        </Button>
        <nav className="flex flex-col gap-0.5">
          {NAV.map(({ to, label, icon: Icon, ...n }) => (
            <NavLink
              key={to}
              to={to}
              end={"end" in n}
              className={({ isActive }) =>
                cn(
                  "flex h-9 items-center gap-2.5 rounded-md px-2.5 text-[14px] font-medium text-soft transition-colors hover:bg-panel hover:text-ink",
                  isActive && "bg-raise text-ink shadow-[0_0_0_1px_var(--line)]",
                )
              }
            >
              <Icon className="size-[17px]" aria-hidden />
              {label}
              {to === "/inbox" && attention > 0 && (
                <span
                  className="ml-auto rounded-full bg-bad px-1.5 text-[11px] leading-[18px] font-semibold text-paper tabular-nums"
                  aria-label={`${attention} need you`}
                >
                  {attention}
                </span>
              )}
              {to === "/inbox" && attention === 0 && working > 0 && (
                <span className="ml-auto text-[12px] text-mut tabular-nums pulse" aria-label={`${working} being read`}>
                  {working}
                </span>
              )}
            </NavLink>
          ))}
        </nav>
        <div className="mt-auto space-y-2 px-2.5 text-[12.5px] text-mut">
          {state.data && <p className="tabular-nums">{state.data.items.toLocaleString()} items saved</p>}
          <button type="button" className="inline-flex items-center gap-1.5 hover:text-ink" onClick={() => setHelp(true)}>
            <Keyboard className="size-3.5" aria-hidden /> Shortcuts <Kbd>?</Kbd>
          </button>
        </div>
      </aside>

      <div className="min-w-0">
        {/* Mobile top bar */}
        <div className="sticky top-0 z-30 flex h-12 items-center justify-between border-b border-hair bg-paper/95 px-4 backdrop-blur md:hidden">
          <span className="font-serif text-[19px] font-semibold">Pith</span>
          <Button variant="primary" size="sm" onClick={open}>
            <Plus className="size-4" aria-hidden /> Save
          </Button>
        </div>
        <main id="main" tabIndex={-1} className="mx-auto w-full max-w-[84rem] px-4 pt-5 pb-28 outline-none md:px-8 md:pt-7 md:pb-16">
          <Outlet />
        </main>
      </div>

      {/* Mobile tab bar */}
      <nav
        aria-label="Primary"
        className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-5 border-t border-line bg-paper/95 pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden"
      >
        {NAV.map(({ to, label, icon: Icon, ...n }) => (
          <NavLink
            key={to}
            to={to}
            end={"end" in n}
            className={({ isActive }) =>
              cn("relative flex h-14 flex-col items-center justify-center gap-0.5 text-[11px] font-medium text-mut", isActive && "text-acc")
            }
          >
            <Icon className="size-5" aria-hidden />
            {"short" in n ? n.short : label}
            {to === "/inbox" && attention > 0 && (
              <span className="absolute top-2 right-[calc(50%-18px)] size-2 rounded-full bg-bad" aria-label={`${attention} need you`} />
            )}
          </NavLink>
        ))}
      </nav>

      <Modal open={help} onOpenChange={setHelp} title="Keyboard shortcuts">
        <dl className="grid grid-cols-[auto_1fr] gap-x-5 gap-y-2 text-[13.5px]">
          {SHORTCUTS.map(([k, d]) => (
            <div key={k} className="contents">
              <dt className="font-mono text-[12.5px] text-soft">{k}</dt>
              <dd className="text-ink">{d}</dd>
            </div>
          ))}
        </dl>
      </Modal>
    </div>
  );
}

export function RouteError() {
  const e = useRouteError();
  const msg = e instanceof ApiError ? e.message : e instanceof Error ? e.message : "Something went wrong.";
  return (
    <div className="p-6">
      <EmptyState title="This page could not load" action={<Button onClick={() => (location.hash = "#/")}>Go to Today</Button>}>
        {msg}
      </EmptyState>
    </div>
  );
}
