import { BookOpen, Home, Inbox, Keyboard, Menu, Moon, Plus, Search, Settings, Sun, TriangleAlert } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate, useRouteError } from "react-router";
import { DeskDialog } from "@/components/desk-dialog";
import { TooltipProvider } from "@/components/overlay";
import { Button, EmptyState } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { useHotkeys } from "@/lib/hotkeys";
import { getTheme, setTheme } from "@/lib/local";
import { useAppState } from "@/lib/queries";
import { useShelfData } from "@/lib/shelf-data";
import { CaptureProvider, useCapture } from "./capture";
import "@/v5-shell.css";

const SHORTCUTS: [string, string][] = [
  ["n", "Save a link, text or file"],
  ["/  or  ⌘K", "Search and ask"],
  ["g h", "Your desk"],
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

function Frame() {
  const nav = useNavigate();
  const loc = useLocation();
  const { open } = useCapture();
  const [help, setHelp] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [dark, setDark] = useState(
    () => getTheme() === "dark" || (getTheme() === "system" && matchMedia("(prefers-color-scheme: dark)").matches),
  );
  const menuTrigger = useRef<HTMLButtonElement>(null);
  const state = useAppState();
  const data = useShelfData();
  const attention = (state.data?.counts.failed ?? 0) + (state.data?.counts.needs_clarification ?? 0);
  const working = (state.data?.counts.pending ?? 0) + (state.data?.counts.processing ?? 0) + (state.data?.counts.new ?? 0);
  const qc = useQueryClient();
  const was = useRef(0);
  useEffect(() => {
    if (was.current > 0 && working === 0) {
      void qc.invalidateQueries({ queryKey: ["library"] });
      void qc.invalidateQueries({ queryKey: ["desk"] });
    }
    was.current = working;
  }, [working, qc]);
  useHotkeys({
    n: (event) => {
      event.preventDefault();
      open();
    },
    "/": (event) => {
      event.preventDefault();
      nav("/search?focus=1");
    },
    "mod+k": (event) => {
      event.preventDefault();
      nav("/search?focus=1");
    },
    "?": () => setHelp(true),
    "g h": () => nav("/"),
    "g s": () => nav("/shelves"),
    "g l": () => nav("/library"),
    "g i": () => nav("/inbox"),
    "g ,": () => nav("/settings"),
  });
  useEffect(() => {
    const main = document.getElementById("main");
    if (main && !main.contains(document.activeElement)) main.focus({ preventScroll: true });
  }, [loc.pathname]);
  useEffect(() => {
    const sync = () =>
      setDark(
        document.documentElement.dataset.theme === "dark" ||
          (!document.documentElement.dataset.theme && matchMedia("(prefers-color-scheme: dark)").matches),
      );
    const observer = new MutationObserver(sync);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    const media = matchMedia("(prefers-color-scheme: dark)");
    media.addEventListener("change", sync);
    return () => {
      observer.disconnect();
      media.removeEventListener("change", sync);
    };
  }, []);
  const blocked = (state.data?.backends ?? []).find((backend) => backend.blocked_reason);
  const sidebarShelves = data.shelves.filter(
    (shelf) => shelf.id === loc.pathname.split("/")[2] || (data.byShelf.get(shelf.id)?.length ?? 0) > 0 || !data.ready,
  );
  const context =
    loc.pathname === "/"
      ? "Your desk"
      : loc.pathname.startsWith("/shelf/")
        ? (data.shelves.find((s) => s.id === loc.pathname.split("/")[2])?.name ?? "Shelves")
        : loc.pathname === "/library"
          ? "All knowledge"
          : loc.pathname.startsWith("/note/")
            ? "Saved knowledge"
            : loc.pathname === "/search"
              ? "Search & ask"
              : loc.pathname === "/inbox"
                ? "Inbox"
                : loc.pathname === "/settings"
                  ? "Settings"
                  : "Shelves";
  const linkClass = ({ isActive }: { isActive: boolean }) => `v5-shell-nav-link${isActive ? " current" : ""}`;
  const dismissNavigation = () => setMenuOpen(false);
  const navigation = () => (
    <>
      <div className="v5-shell-brand">Pith</div>
      <nav aria-label="Main navigation">
        <NavLink to="/" end onClick={dismissNavigation} className={linkClass}>
          <Home size={17} aria-hidden />
          Your desk
        </NavLink>
        <NavLink to="/library" onClick={dismissNavigation} className={linkClass}>
          <BookOpen size={17} aria-hidden />
          All knowledge{data.ready && <span className="v5-shell-count">{data.total.toLocaleString()}</span>}
        </NavLink>
        <NavLink to="/search" onClick={dismissNavigation} className={linkClass}>
          <Search size={17} aria-hidden />
          Search
        </NavLink>
      </nav>
      <div className="v5-shell-shelves">
        <div className="v5-shell-shelf-heading">
          <h2>Shelves</h2>
          <Link to="/shelves" onClick={dismissNavigation}>
            All shelves
          </Link>
        </div>
        <nav aria-label="Shelves">
          {sidebarShelves.map((shelf) => {
            const list = data.byShelf.get(shelf.id) ?? [];
            const count = shelf.todo ? list.filter((p) => !p.state.done).length : list.length;
            return (
              <NavLink key={shelf.id} to={`/shelf/${shelf.id}`} onClick={dismissNavigation} className={linkClass}>
                <span>{shelf.name}</span>
                {data.ready && <span className="v5-shell-count">{count.toLocaleString()}</span>}
              </NavLink>
            );
          })}
        </nav>
      </div>
      <div className="v5-shell-bottom">
        <p>A place to return to.</p>
        <NavLink to="/inbox" className={linkClass} onClick={dismissNavigation}>
          <Inbox size={17} aria-hidden />
          Inbox
          {attention > 0 ? (
            <span className="v5-shell-count v5-shell-attention" aria-label={`${attention} need you`}>
              {attention}
            </span>
          ) : working > 0 ? (
            <span className="v5-shell-count" aria-label={`${working} being read`}>
              {working}
            </span>
          ) : null}
        </NavLink>
        <NavLink to="/settings" className={linkClass} onClick={dismissNavigation}>
          <Settings size={17} aria-hidden />
          Settings
        </NavLink>
        {blocked && (
          <Link to="/settings" className="v5-shell-nav-link" onClick={dismissNavigation}>
            <TriangleAlert size={17} aria-hidden />
            <span>Model unavailable</span>
          </Link>
        )}
        <button
          type="button"
          className="v5-shell-nav-link"
          onClick={() => {
            setMenuOpen(false);
            setHelp(true);
          }}
        >
          <Keyboard size={17} aria-hidden />
          Keyboard shortcuts
        </button>
      </div>
    </>
  );
  return (
    <div className="v5-shell">
      <a href="#main" className="v5-shell-skip">
        Skip to content
      </a>
      <aside className="v5-shell-sidebar" aria-label="Primary">
        {navigation()}
      </aside>
      {menuOpen && (
        <DeskDialog title="Your Pith" opener={menuTrigger.current} onClose={() => setMenuOpen(false)}>
          <div className="v5-dialog-body v5-shell-mobile-nav">{navigation()}</div>
        </DeskDialog>
      )}
      <div className="v5-shell-content">
        <header className="v5-shell-topbar">
          <button
            ref={menuTrigger}
            type="button"
            className="v5-icon-button v5-shell-menu"
            aria-label="Open navigation"
            onClick={() => setMenuOpen(true)}
          >
            <Menu size={20} aria-hidden />
          </button>
          <span className="v5-shell-context">{context}</span>
          <form
            role="search"
            className="v5-shell-search"
            onSubmit={(event) => {
              event.preventDefault();
              nav(`/search?q=${encodeURIComponent(query)}`);
            }}
          >
            <Search size={17} aria-hidden />
            <label className="sr-only" htmlFor="global-search">
              Find saved knowledge
            </label>
            <input
              id="global-search"
              type="search"
              placeholder="Find something you saved…"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
            <kbd aria-hidden>⌘ K</kbd>
          </form>
          <div className="v5-shell-actions">
            <button
              type="button"
              className="v5-icon-button v5-shell-theme"
              aria-label={dark ? "Switch to light theme" : "Switch to dark theme"}
              onClick={() => setTheme(dark ? "light" : "dark")}
            >
              {dark ? <Sun size={18} aria-hidden /> : <Moon size={18} aria-hidden />}
            </button>
            <button type="button" className="v5-shell-save" onClick={open}>
              <Plus size={17} aria-hidden />
              Save
            </button>
          </div>
        </header>
        <main id="main" tabIndex={-1} className="v5-shell-main">
          <Outlet />
        </main>
      </div>
      {help && (
        <DeskDialog title="Keyboard shortcuts" onClose={() => setHelp(false)}>
          <div className="v5-dialog-body">
            <dl className="grid grid-cols-[auto_1fr] gap-x-5 gap-y-2 text-[13.5px]">
              {SHORTCUTS.map(([key, description]) => (
                <div key={key} className="contents">
                  <dt className="font-mono text-[12.5px] text-soft">{key}</dt>
                  <dd>{description}</dd>
                </div>
              ))}
            </dl>
          </div>
        </DeskDialog>
      )}
    </div>
  );
}

export function RouteError() {
  const error = useRouteError();
  const message = error instanceof ApiError ? error.message : error instanceof Error ? error.message : "Something went wrong.";
  return (
    <div className="p-6">
      <EmptyState title="This page could not load" action={<Button onClick={() => (location.hash = "#/")}>Go to Home</Button>}>
        {message}
      </EmptyState>
    </div>
  );
}
