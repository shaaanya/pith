import { BookOpen, ChevronDown, Home, Inbox, Keyboard, LibraryBig, PanelLeftClose, PanelLeftOpen, Plus, Search, Settings, TriangleAlert } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate, useRouteError } from "react-router";
import { Modal, TooltipProvider } from "@/components/overlay";
import { ShelfIcon } from "@/components/shelf-bits";
import { Button, EmptyState, Kbd } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { useHotkeys } from "@/lib/hotkeys";
import { useAppState } from "@/lib/queries";
import { useShelfData } from "@/lib/shelf-data";
import { layout, usePrefs } from "@/lib/shelves";
import { cn } from "@/lib/utils";
import { CaptureProvider, useCapture } from "./capture";

const SHORTCUTS: [string, string][] = [
  ["n", "Save a link, text or file"],
  ["/  or  ⌘K", "Search and ask"],
  ["g h", "Home"],
  ["g s", "Shelves"],
  ["g l", "All knowledge"],
  ["g i", "Inbox"],
  ["g ,", "Settings"],
  ["j / k", "Next / previous in a list"],
  ["Enter", "Open the selected note"],
  ["x", "Select the focused row (All knowledge)"],
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

const navLink = (rail: boolean) => ({ isActive }: { isActive: boolean }) =>
  cn(
    "group flex h-8 items-center gap-2.5 rounded-md px-2.5 text-[13.5px] font-medium text-soft transition-colors hover:bg-panel hover:text-ink",
    rail && "justify-center px-0",
    isActive && "bg-panel text-ink shadow-[inset_2px_0_0_var(--acc)]",
  );

function Frame() {
  const nav = useNavigate();
  const loc = useLocation();
  const { open } = useCapture();
  const [help, setHelp] = useState(false);
  const state = useAppState();
  const data = useShelfData();
  const m = usePrefs();
  const attention = (state.data?.counts.failed ?? 0) + (state.data?.counts.needs_clarification ?? 0);
  const working = (state.data?.counts.pending ?? 0) + (state.data?.counts.processing ?? 0) + (state.data?.counts.new ?? 0);

  // When reading finishes, refresh the notes index so shelves pick up what just arrived.
  const qc = useQueryClient();
  const was = useRef(0);
  useEffect(() => {
    if (was.current > 0 && working === 0) void qc.invalidateQueries({ queryKey: ["library"] });
    was.current = working;
  }, [working, qc]);

  useHotkeys({
    n: (e) => (e.preventDefault(), open()),
    "/": (e) => (e.preventDefault(), nav("/search?focus=1")),
    "mod+k": (e) => (e.preventDefault(), nav("/search?focus=1")),
    "?": () => setHelp(true),
    "g h": () => nav("/"),
    "g s": () => nav("/shelves"),
    "g l": () => nav("/library"),
    "g i": () => nav("/inbox"),
    "g ,": () => nav("/settings"),
  });

  // Move focus to the page on navigation so keyboard and screen-reader users start at the content.
  useEffect(() => {
    const main = document.getElementById("main");
    if (main && !main.contains(document.activeElement)) main.focus({ preventScroll: true });
  }, [loc.pathname]);

  const onShelves = loc.pathname.startsWith("/shelf");
  const rail = m.rail;
  const link = navLink(rail);
  const blocked = (state.data?.backends ?? []).find((b) => b.blocked_reason);
  const sidebarShelves = data.shelves.filter((s) => s.id === loc.pathname.split("/")[2] || (data.byShelf.get(s.id)?.length ?? 0) > 0 || !data.ready);
  const label = (t: React.ReactNode) => (rail ? <span className="sr-only">{t}</span> : <>{t}</>);
  const wide = loc.pathname === "/";

  return (
    <div className={cn("min-h-dvh md:grid", rail ? "md:grid-cols-[3.75rem_minmax(0,1fr)]" : "md:grid-cols-[15.5rem_minmax(0,1fr)]")}>
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-[80] focus:rounded-md focus:bg-acc focus:px-3 focus:py-1.5 focus:text-acc-ink"
      >
        Skip to content
      </a>

      {/* Desktop sidebar: full, or a 3.75rem icon rail */}
      <aside
        className={cn("sticky top-0 hidden h-dvh flex-col gap-4 overflow-y-auto border-r border-hair bg-side pt-5 pb-3 md:flex", rail ? "px-2" : "px-3")}
        aria-label="Primary"
      >
        <div className={cn("flex items-center px-2", rail ? "flex-col gap-2" : "justify-between")}>
          {rail ? <span className="font-serif text-[20px] leading-none font-semibold">P</span> : <span className="font-serif text-[23px] leading-none font-semibold tracking-tight">Pith</span>}
          <Button size="iconSm" variant="ghost" onClick={open} aria-label="Save something (n)" title="Save something (n)">
            <Plus className="size-[18px]" aria-hidden />
          </Button>
        </div>

        <nav className="flex flex-col gap-0.5" aria-label="Main">
          <NavLink to="/" end className={link} title="Home">
            <Home className="size-[17px]" aria-hidden /> {label("Home")}
          </NavLink>
          <NavLink to="/library" className={link} title="All knowledge">
            <BookOpen className="size-[17px]" aria-hidden /> {label("All knowledge")}
            {!rail && data.ready && <span className="ml-auto text-[12px] text-mut tabular-nums">{data.total.toLocaleString()}</span>}
          </NavLink>
          <NavLink to="/search" className={link} title="Search & ask">
            <Search className="size-[17px]" aria-hidden /> {label("Search & ask")}
            {!rail && (
              <span className="ml-auto opacity-0 transition-opacity group-hover:opacity-100">
                <Kbd>/</Kbd>
              </span>
            )}
          </NavLink>
          <NavLink to="/inbox" className={link} title="Inbox">
            <Inbox className="size-[17px]" aria-hidden /> {label("Inbox")}
            {attention > 0 ? (
              <span
                className={cn("ml-auto rounded-full bg-bad px-1.5 text-[11px] leading-[18px] font-semibold text-paper tabular-nums", rail && "absolute top-0.5 right-0.5 ml-0 scale-75")}
                aria-label={`${attention} need you`}
              >
                {attention}
              </span>
            ) : (
              working > 0 &&
              !rail && (
                <span className="pulse ml-auto text-[12px] text-mut tabular-nums" aria-label={`${working} being read`}>
                  {working}
                </span>
              )
            )}
          </NavLink>
        </nav>

        <nav aria-label="Shelves" className={cn("min-h-0", data.ready && sidebarShelves.length === 0 && "hidden")}>
          {!rail && (
            <div className="mb-1 flex items-center justify-between px-2.5">
              <button
                type="button"
                aria-expanded={!m.collapsed}
                onClick={() => layout.collapse(!m.collapsed)}
                className="flex min-h-8 items-center gap-1 text-[11.5px] font-semibold tracking-[0.07em] text-mut uppercase hover:text-ink"
              >
                <ChevronDown className={cn("size-3.5 transition-transform", m.collapsed && "-rotate-90")} aria-hidden />
                Shelves
              </button>
              <NavLink to="/shelves" end className="inline-flex min-h-8 items-center text-[12px] text-mut hover:text-ink" aria-label="All shelves and shelf settings">
                All shelves
              </NavLink>
            </div>
          )}
          {(rail || !m.collapsed) && (
            <ul className="flex flex-col gap-0.5">
              {sidebarShelves.map((s) => {
                const list = data.byShelf.get(s.id) ?? [];
                const n = s.todo ? list.filter((p) => !p.state.done).length : list.length;
                return (
                  <li key={s.id}>
                    <NavLink to={`/shelf/${s.id}`} className={link} title={`${s.name}${data.ready ? ` (${n})` : ""}`}>
                      <ShelfIcon id={s.id} className="text-mut group-hover:text-ink" />
                      {label(<span className="truncate">{s.name}</span>)}
                      {!rail && data.ready && (
                        <span className="ml-auto text-[12px] text-mut tabular-nums" aria-label={`${n} ${s.todo ? "to do" : "notes"}`}>
                          {n || ""}
                        </span>
                      )}
                    </NavLink>
                  </li>
                );
              })}
            </ul>
          )}
        </nav>

        <div className="mt-auto space-y-0.5">
          <NavLink to="/settings" className={link} title="Settings">
            <Settings className="size-[17px]" aria-hidden /> {label("Settings")}
          </NavLink>
          {blocked && (
            <Link
              to="/settings"
              title={blocked.blocked_reason ?? undefined}
              className={cn("flex h-8 items-center gap-2.5 rounded-md px-2.5 text-[12.5px] text-warn hover:bg-panel", rail && "justify-center px-0")}
            >
              <TriangleAlert className="size-[17px]" aria-hidden />
              {rail ? <span className="sr-only">Model unavailable</span> : <span className="truncate">Model unavailable</span>}
            </Link>
          )}
          <div className={cn("flex", rail ? "flex-col" : "gap-0.5")}>
            <button
              type="button"
              className={cn("flex h-8 items-center gap-2.5 rounded-md px-2.5 text-[12.5px] text-mut hover:bg-panel hover:text-ink", rail ? "justify-center px-0" : "flex-1")}
              onClick={() => setHelp(true)}
              title="Keyboard shortcuts (?)"
            >
              <Keyboard className="size-[17px]" aria-hidden />
              {rail ? <span className="sr-only">Shortcuts</span> : <>Shortcuts <span className="ml-auto"><Kbd>?</Kbd></span></>}
            </button>
            <button
              type="button"
              onClick={() => layout.rail(!rail)}
              aria-label={rail ? "Expand sidebar" : "Collapse sidebar"}
              title={rail ? "Expand sidebar" : "Collapse sidebar"}
              className={cn("grid h-8 w-8 place-items-center rounded-md text-mut hover:bg-panel hover:text-ink", rail && "w-full")}
            >
              {rail ? <PanelLeftOpen className="size-[17px]" aria-hidden /> : <PanelLeftClose className="size-[17px]" aria-hidden />}
            </button>
          </div>
        </div>
      </aside>

      <div className="min-w-0">
        {/* Mobile top bar */}
        <div className="sticky top-0 z-30 flex h-12 items-center justify-between gap-1 border-b border-hair bg-paper/95 pr-2 pl-4 backdrop-blur md:hidden">
          <span className="mr-auto font-serif text-[20px] font-semibold">Pith</span>
          <Link to={attention > 0 ? "/inbox?show=attention" : "/inbox"} className="relative grid size-11 place-items-center rounded-md text-soft" aria-label={attention > 0 ? `Inbox, ${attention} need you` : working > 0 ? `Inbox, ${working} being read` : "Inbox"}>
            <Inbox className="size-5" aria-hidden />
            {attention > 0 && <span className="absolute top-2.5 right-2.5 size-2 rounded-full bg-bad" aria-hidden />}
            {attention === 0 && working > 0 && <span className="pulse absolute top-2.5 right-2.5 size-2 rounded-full bg-acc" aria-hidden />}
          </Link>
          <Link to="/settings" className="grid size-11 place-items-center rounded-md text-soft" aria-label="Settings">
            <Settings className="size-5" aria-hidden />
          </Link>
          <Button variant="primary" size="md" onClick={open}>
            <Plus className="size-4" aria-hidden /> Save
          </Button>
        </div>
        <main id="main" tabIndex={-1} className={cn("mx-auto w-full px-4 pt-5 pb-28 outline-none md:px-8 md:pt-8 md:pb-20 xl:px-10", wide ? "max-w-[104rem]" : "max-w-[78rem] md:px-10 md:pt-9")}>
          <Outlet />
        </main>
      </div>

      {/* Mobile tab bar: the four places you go to find things. Inbox and Settings live in the top bar. */}
      <nav
        aria-label="Primary"
        className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-4 border-t border-line bg-paper/95 pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden"
      >
        {(
          [
            ["/", "Home", Home, undefined],
            ["/shelves", "Shelves", LibraryBig, onShelves],
            ["/search", "Search", Search, undefined],
            ["/library", "All", BookOpen, undefined],
          ] as const
        ).map(([to, label, Icon, force]) => (
          <NavLink
            key={to}
            to={to}
            end={to === "/"}
            className={({ isActive }) =>
              cn("relative flex h-14 flex-col items-center justify-center gap-0.5 text-[11px] font-medium text-mut", (force ?? isActive) && "text-acc")
            }
          >
            <Icon className="size-5" aria-hidden />
            {label}
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
      <EmptyState title="This page could not load" action={<Button onClick={() => (location.hash = "#/")}>Go to Home</Button>}>
        {msg}
      </EmptyState>
    </div>
  );
}
