import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  ArrowDown,
  ArrowUp,
  BookOpen,
  Bookmark,
  Check,
  ChevronDown,
  ChevronRight,
  Compass,
  Database,
  Focus,
  Home,
  Layers,
  Menu,
  Moon,
  MoreHorizontal,
  Plus,
  Search,
  Settings2,
  Sun,
  Terminal,
  X,
} from "lucide-react";
import {
  makeDataset,
  shelves,
  type Dataset,
  type Group,
  type Item,
  type Shelf,
  type Workspace,
} from "./data";
import { fresh, useDesk, type DeskState } from "./state";
import { Dialog } from "./Dialog";
import { Reader } from "./Reader";
import { GroupEditor } from "./GroupEditor";

type Overlay =
  | { kind: "reader"; id: string }
  | { kind: "edit"; groupId?: string }
  | { kind: "group"; groupId: string }
  | { kind: "settings" }
  | { kind: "capture" };
const groupIcons: Record<string, typeof Bookmark> = {
  database: Database,
  terminal: Terminal,
  book: BookOpen,
  compass: Compass,
  layers: Layers,
  bookmark: Bookmark,
};

function ItemRows({
  items,
  onOpen,
}: {
  items: Item[];
  onOpen: (item: Item, invoker: HTMLElement) => void;
}) {
  return (
    <ul className="item-list">
      {items.map((item) => (
        <li key={item.id}>
          <button
            className="item-row"
            onClick={(e) => onOpen(item, e.currentTarget)}
          >
            <span className="item-row-title">{item.title}</span>
            <span className="item-row-type">{item.type}</span>
            <ChevronRight size={15} aria-hidden="true" />
          </button>
        </li>
      ))}
    </ul>
  );
}

/** Prototype-owned runtime. There are deliberately no imports from frontend/src. */
export function App() {
  const { state, setState, storageUnavailable } = useDesk();
  const [page, setPage] = useState<"desk" | "library" | "shelf">("desk");
  const [shelf, setShelf] = useState<Shelf>("Read");
  const [navOpen, setNavOpen] = useState(false);
  const [arranging, setArranging] = useState(false);
  const [overlay, setOverlay] = useState<Overlay | null>(null);
  const [query, setQuery] = useState("");
  const [limit, setLimit] = useState(30);
  const [shown, setShown] = useState<Record<string, number>>({});
  const [toast, setToast] = useState("");
  const [undo, setUndo] = useState<DeskState | null>(null);
  const [undoMessage, setUndoMessage] = useState("");
  const [history, setHistory] = useState<{ id: string; scroll: number }[]>([]);
  const [readingState, setReadingState] = useState<
    "ready" | "loading" | "error"
  >("ready");
  const opener = useRef<HTMLElement | null>(null);
  const navFocus = useRef<HTMLElement | null>(null);
  const navAction = useRef<(() => void) | null>(null);
  const [readerPosition, setReaderPosition] = useState(0);
  const pageScroll = useRef<Record<Workspace, number>>({
    focus: 0,
    overview: 0,
  });
  const search = useRef<HTMLInputElement>(null);
  const { items } = useMemo(() => makeDataset(state.dataset), [state.dataset]);
  const byId = useMemo(() => new Map(items.map((i) => [i.id, i])), [items]);
  const activeGroups = state.groups.filter(
    (g) => state.workspace === "overview" || state.focused.includes(g.id),
  );
  const filtered = useMemo(
    () =>
      items.filter(
        (i) =>
          (page !== "shelf" || i.shelf === shelf) &&
          `${i.title} ${i.lead} ${i.topics.join(" ")}`
            .toLowerCase()
            .includes(query.toLowerCase()),
      ),
    [items, page, shelf, query],
  );
  const announce = (text: string) => setToast(text);
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(""), 5000);
    return () => clearTimeout(t);
  }, [toast]);
  useEffect(() => {
    document.title = `${page === "desk" ? "Your desk" : page === "shelf" ? shelf : "All knowledge"} · Pith prototype`;
  }, [page, shelf]);
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (document.querySelector("dialog[open]")) return;
      const editing =
        e.target instanceof HTMLElement &&
        !!e.target.closest("input,textarea,[contenteditable]");
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        search.current?.focus();
      } else if (e.key === "/" && !editing) {
        e.preventDefault();
        search.current?.focus();
      }
    };
    document.addEventListener("keydown", key);
    return () => document.removeEventListener("keydown", key);
  }, []);
  function open(next: Overlay, invoker?: HTMLElement | null) {
    opener.current =
      invoker ??
      (document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null);
    setReaderPosition(0);
    setHistory([]);
    setOverlay(next);
  }
  function openItem(item: Item, invoker: HTMLElement) {
    open({ kind: "reader", id: item.id }, invoker);
  }
  function navigate(next: "desk" | "library" | "shelf", target?: Shelf) {
    setPage(next);
    if (target) setShelf(target);
    setQuery("");
    setLimit(30);
    if (navOpen) {
      navFocus.current ??= document.getElementById("page-title");
      document.querySelector<HTMLDialogElement>("dialog[open]")?.close();
    }
    setArranging(false);
    window.scrollTo(0, 0);
  }
  function workspace(next: Workspace) {
    if (next === state.workspace) return;
    pageScroll.current[state.workspace] = window.scrollY;
    setState((s) => ({ ...s, workspace: next }));
    setArranging(false);
    requestAnimationFrame(() =>
      window.scrollTo({ top: pageScroll.current[next], behavior: "instant" }),
    );
  }
  function updateOrganization(
    change: (s: DeskState) => DeskState,
    message: string,
  ) {
    setUndo(structuredClone(state));
    setUndoMessage(message);
    setState(change(state));
    announce(message);
  }
  function focusGroup(group: Group) {
    const added = !state.focused.includes(group.id);
    updateOrganization(
      (s) => ({
        ...s,
        focused: added
          ? [...s.focused, group.id]
          : s.focused.filter((id) => id !== group.id),
      }),
      `${group.title} ${added ? "added to" : "removed from"} Focus`,
    );
  }
  function move(group: Group, direction: -1 | 1) {
    const visible = activeGroups;
    const i = visible.findIndex((g) => g.id === group.id);
    const neighbor = visible[i + direction];
    if (!neighbor) return;
    updateOrganization(
      (s) => {
        const list = [...s.groups];
        const a = list.findIndex((g) => g.id === group.id),
          b = list.findIndex((g) => g.id === neighbor.id);
        [list[a], list[b]] = [list[b], list[a]];
        return { ...s, groups: list };
      },
      `${group.title} moved to position ${i + direction + 1} of ${visible.length}`,
    );
    requestAnimationFrame(() =>
      document
        .getElementById(`trigger-${group.id}`)
        ?.focus({ preventScroll: true }),
    );
  }
  function save(group: Group) {
    const exists = state.groups.some((g) => g.id === group.id);
    updateOrganization(
      (s) => ({
        ...s,
        groups: exists
          ? s.groups.map((g) => (g.id === group.id ? group : g))
          : [...s.groups, group],
      }),
      `${group.title} saved`,
    );
    document.querySelector<HTMLDialogElement>("dialog[open]")?.close();
  }
  function changeDataset(dataset: Dataset) {
    setState((s) => ({ ...fresh(dataset), theme: s.theme }));
    setUndo(null);
    setShown({});
    setQuery("");
    setPage("desk");
    setArranging(false);
    pageScroll.current = { focus: 0, overview: 0 };
    announce(`${dataset} example collection loaded`);
  }
  const current = overlay?.kind === "reader" ? byId.get(overlay.id) : undefined;
  const selectedGroup =
    overlay && (overlay.kind === "group" || overlay.kind === "edit")
      ? state.groups.find((g) => g.id === overlay.groupId)
      : undefined;
  let overlayTitle =
    overlay?.kind === "reader"
      ? (current?.title ?? "Item unavailable")
      : overlay?.kind === "edit"
        ? selectedGroup
          ? "Edit group"
          : "New group"
        : overlay?.kind === "group"
          ? (selectedGroup?.title ?? "Group options")
          : overlay?.kind === "capture"
            ? "Save to your sample library"
            : "Prototype settings";

  function navigation(): ReactNode {
    return (
      <>
        <div className="brand">
          <span>Pith</span>
          <span className="prototype-tag">Prototype</span>
          {navOpen && (
            <button
              className="icon-button mobile-close"
              aria-label="Close navigation"
              onClick={(e) => e.currentTarget.closest("dialog")?.close()}
            >
              <X size={20} />
            </button>
          )}
        </div>
        <nav aria-label="Main navigation">
          <button
            className={page === "desk" ? "nav-link current" : "nav-link"}
            aria-current={page === "desk" ? "page" : undefined}
            onClick={() => navigate("desk")}
          >
            <Home size={17} />
            Your desk
          </button>
          <button
            className={page === "library" ? "nav-link current" : "nav-link"}
            aria-current={page === "library" ? "page" : undefined}
            onClick={() => navigate("library")}
          >
            <BookOpen size={17} />
            All knowledge
          </button>
          <button
            className="nav-link"
            onClick={() => {
              if (navOpen) navFocus.current = search.current;
              navigate("library");
              if (!navOpen) search.current?.focus();
            }}
          >
            <Search size={17} />
            Search
          </button>
        </nav>
        <div className="shelf-nav">
          <h2>Shelves</h2>
          <nav aria-label="Shelves">
            {shelves.map((name) => (
              <button
                key={name}
                className={
                  page === "shelf" && shelf === name
                    ? "nav-link current"
                    : "nav-link"
                }
                aria-current={
                  page === "shelf" && shelf === name ? "page" : undefined
                }
                onClick={() => navigate("shelf", name)}
              >
                <span>{name}</span>
                <span className="nav-count">
                  {items
                    .filter((i) => i.shelf === name)
                    .length.toLocaleString()}
                </span>
              </button>
            ))}
          </nav>
        </div>
        <div className="sidebar-bottom">
          <p>A place to return to.</p>
          <button
            className="nav-link"
            onClick={(e) => {
              if (navOpen) {
                const menu = document.getElementById("navigation-toggle");
                navAction.current = () => open({ kind: "settings" }, menu);
                document
                  .querySelector<HTMLDialogElement>("dialog[open]")
                  ?.close();
              } else open({ kind: "settings" }, e.currentTarget);
            }}
          >
            <Settings2 size={17} />
            Prototype settings
          </button>
          <small>Example knowledge · browser-local changes</small>
        </div>
      </>
    );
  }

  return (
    <>
      <a href="#main" className="skip-link">
        Skip to content
      </a>
      <aside className="sidebar">{navigation()}</aside>
      {navOpen && (
        <Dialog
          title="Your Pith"
          opener={opener.current}
          restoreFocus={() => {
            if (navFocus.current)
              window.scrollTo({ top: 0, behavior: "instant" });
            return (
              navFocus.current ?? document.getElementById("navigation-toggle")
            );
          }}
          onClose={() => {
            setNavOpen(false);
            const action = navAction.current;
            navAction.current = null;
            action?.();
          }}
        >
          <div className="mobile-navigation modal-body">{navigation()}</div>
        </Dialog>
      )}
      <div className="app-content">
        <header className="topbar">
          <button
            id="navigation-toggle"
            className="icon-button menu-button"
            aria-label="Open navigation"
            onClick={() => {
              navFocus.current = null;
              opener.current = document.getElementById("navigation-toggle");
              setNavOpen(true);
            }}
          >
            <Menu size={20} />
          </button>
          <span className="topbar-context">
            {page === "desk"
              ? "Your desk"
              : page === "shelf"
                ? shelf
                : "All knowledge"}
          </span>
          <form
            role="search"
            className="search-box"
            onSubmit={(e) => {
              e.preventDefault();
              setPage("library");
              setLimit(30);
            }}
          >
            <Search size={17} aria-hidden="true" />
            <label className="sr-only" htmlFor="global-search">
              Search example knowledge
            </label>
            <input
              ref={search}
              id="global-search"
              type="search"
              placeholder="Find something you saved…"
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setLimit(30);
                if (e.target.value) {
                  setPage("library");
                  setArranging(false);
                }
              }}
            />
            <kbd aria-hidden="true">⌘ K</kbd>
          </form>
          <div className="topbar-actions">
            <button
              className="icon-button"
              aria-label={
                state.theme === "light"
                  ? "Switch to dark theme"
                  : "Switch to light theme"
              }
              onClick={() =>
                setState((s) => ({
                  ...s,
                  theme: s.theme === "light" ? "dark" : "light",
                }))
              }
            >
              {state.theme === "light" ? <Moon size={18} /> : <Sun size={18} />}
            </button>
            <button
              className="primary-button save-button"
              onClick={(e) => open({ kind: "capture" }, e.currentTarget)}
            >
              <Plus size={17} />
              Save
            </button>
          </div>
        </header>
        <main id="main" tabIndex={-1} className="desk-main">
          <header className="page-header">
            <div>
              <h1 id="page-title" tabIndex={-1}>
                {page === "desk"
                  ? "Your Working Desk"
                  : page === "shelf"
                    ? shelf
                    : "All knowledge"}
              </h1>
              <p>
                {page === "desk"
                  ? state.workspace === "focus"
                    ? "A few chosen contexts, kept within reach."
                    : "Your contexts, ready when you are. Open a group to follow a thread."
                  : page === "shelf"
                    ? "Browse saved knowledge by what it is for."
                    : "Everything saved, with room to find it again."}
              </p>
            </div>
            {page === "desk" && (
              <div className="desk-controls">
                <div
                  className="workspace-switch"
                  role="group"
                  aria-label="Workspace"
                >
                  <button
                    aria-pressed={state.workspace === "focus"}
                    onClick={() => workspace("focus")}
                  >
                    <Focus size={15} />
                    Focus
                    {state.focused.length > 0 && (
                      <span className="workspace-count">
                        {state.focused.length}
                      </span>
                    )}
                  </button>
                  <button
                    aria-pressed={state.workspace === "overview"}
                    onClick={() => workspace("overview")}
                  >
                    Overview
                  </button>
                </div>
                <div className="desk-utilities">
                  <button
                    className="quiet-button"
                    aria-pressed={arranging}
                    onClick={() => setArranging((v) => !v)}
                  >
                    {arranging ? <Check size={16} /> : <Settings2 size={16} />}{" "}
                    {arranging ? "Finish arranging" : "Arrange"}
                  </button>
                  <button
                    className="quiet-button accent"
                    onClick={(e) => open({ kind: "edit" }, e.currentTarget)}
                  >
                    <Plus size={16} />
                    New group
                  </button>
                </div>
              </div>
            )}
          </header>
          {storageUnavailable && (
            <p className="notice">
              Browser storage is unavailable. Your changes will last for this
              visit only.
            </p>
          )}
          {arranging && (
            <p className="arrange-hint">
              Move groups into an order that feels familiar. Changes stay in
              this browser; you can undo the last change.
            </p>
          )}
          {page === "desk" ? (
            <>
              {activeGroups.length === 0 ? (
                <div className="empty-state">
                  <Bookmark size={24} />
                  <h2>
                    {state.workspace === "focus"
                      ? "Choose what stays close"
                      : state.groups.length
                        ? "No groups to show"
                        : "A little room for what matters"}
                  </h2>
                  <p>
                    {state.workspace === "focus"
                      ? "Add a group to Focus from its group options. Your other groups will still be in Overview."
                      : items.length
                        ? "Make a group around a question, a weekend, or something you are exploring."
                        : "There is no saved knowledge in this example collection yet. You can create an empty group or explore the sample collection."}
                  </p>
                  <div className="empty-actions">
                    {state.workspace === "focus" ? (
                      <button
                        className="primary-button"
                        onClick={() => workspace("overview")}
                      >
                        Go to Overview
                      </button>
                    ) : (
                      <button
                        className="primary-button"
                        onClick={(e) => open({ kind: "edit" }, e.currentTarget)}
                      >
                        Create a group
                      </button>
                    )}
                    {items.length === 0 && (
                      <button
                        className="quiet-button"
                        onClick={() => changeDataset("sparse")}
                      >
                        Explore sample knowledge
                      </button>
                    )}
                  </div>
                </div>
              ) : (
                <div className="group-grid">
                  {activeGroups.map((group, index) => {
                    const expanded = state.expanded[state.workspace].includes(
                      group.id,
                    );
                    const Icon = groupIcons[group.icon] ?? Bookmark;
                    const groupItems = group.itemIds
                      .map((id) => byId.get(id))
                      .filter((i): i is Item => !!i);
                    const count = shown[group.id] ?? 5;
                    return (
                      <section
                        className={`group-card${expanded ? " expanded" : ""}`}
                        key={group.id}
                        data-group-id={group.id}
                      >
                        <div className="group-heading">
                          <h2>
                            <button
                              className="group-trigger"
                              id={`trigger-${group.id}`}
                              aria-expanded={expanded}
                              aria-controls={`panel-${group.id}`}
                              onClick={() =>
                                setState((s) => ({
                                  ...s,
                                  expanded: {
                                    ...s.expanded,
                                    [s.workspace]: expanded
                                      ? s.expanded[s.workspace].filter(
                                          (id) => id !== group.id,
                                        )
                                      : [...s.expanded[s.workspace], group.id],
                                  },
                                }))
                              }
                            >
                              <span className="group-symbol">
                                <Icon size={18} />
                              </span>
                              <span className="group-label">
                                <span>{group.title}</span>
                                {group.description && (
                                  <small>{group.description}</small>
                                )}
                              </span>
                              <span className="group-count">
                                {groupItems.length}
                                <span className="sr-only"> items</span>
                              </span>
                              <ChevronDown className="disclosure" size={17} />
                            </button>
                          </h2>
                          <button
                            className="icon-button group-options"
                            aria-label={`Options for ${group.title}`}
                            onClick={(e) =>
                              open(
                                { kind: "group", groupId: group.id },
                                e.currentTarget,
                              )
                            }
                          >
                            <MoreHorizontal size={18} />
                          </button>
                        </div>
                        {arranging && (
                          <div className="arrange-tools">
                            <button
                              className="quiet-button"
                              aria-label={`Move ${group.title} up`}
                              disabled={index === 0}
                              onClick={() => move(group, -1)}
                            >
                              <ArrowUp size={15} />
                              Move up
                            </button>
                            <button
                              className="quiet-button"
                              aria-label={`Move ${group.title} down`}
                              disabled={index === activeGroups.length - 1}
                              onClick={() => move(group, 1)}
                            >
                              <ArrowDown size={15} />
                              Move down
                            </button>
                          </div>
                        )}
                        <div
                          id={`panel-${group.id}`}
                          hidden={!expanded}
                          className="group-panel"
                        >
                          {groupItems.length ? (
                            <ItemRows
                              items={groupItems.slice(0, count)}
                              onOpen={openItem}
                            />
                          ) : (
                            <div className="empty-group">
                              <p>Nothing in this group yet.</p>
                              <button
                                className="quiet-button accent"
                                onClick={(e) =>
                                  open(
                                    { kind: "edit", groupId: group.id },
                                    e.currentTarget,
                                  )
                                }
                              >
                                Choose items
                              </button>
                            </div>
                          )}
                          {groupItems.length > 5 && (
                            <div className="list-continuation">
                              {count < groupItems.length ? (
                                <button
                                  className="quiet-button"
                                  onClick={() => {
                                    setShown((s) => ({
                                      ...s,
                                      [group.id]: Math.min(
                                        count + 10,
                                        groupItems.length,
                                      ),
                                    }));
                                    announce(
                                      `More items shown in ${group.title}`,
                                    );
                                  }}
                                >
                                  {groupItems.length - count <= 10
                                    ? `Show remaining ${groupItems.length - count} ${groupItems.length - count === 1 ? "item" : "items"}`
                                    : "Show 10 more"}
                                </button>
                              ) : (
                                <button
                                  className="quiet-button"
                                  onClick={() => {
                                    setShown((s) => ({ ...s, [group.id]: 5 }));
                                    announce(
                                      `Showing the first 5 items in ${group.title}`,
                                    );
                                  }}
                                >
                                  Show fewer
                                </button>
                              )}
                              <span className="muted">
                                {Math.min(count, groupItems.length)} of{" "}
                                {groupItems.length}
                              </span>
                            </div>
                          )}
                        </div>
                      </section>
                    );
                  })}
                </div>
              )}
            </>
          ) : (
            <section className="library-results" aria-label="Saved knowledge">
              <div className="results-caption">
                <span>
                  {filtered.length.toLocaleString()}{" "}
                  {filtered.length === 1 ? "item" : "items"}
                  {query && ` matching “${query}”`}
                </span>
                {query && (
                  <button
                    className="quiet-button"
                    onClick={() => {
                      setQuery("");
                      setLimit(30);
                    }}
                  >
                    Clear search
                  </button>
                )}
              </div>
              {filtered.length ? (
                <>
                  <ItemRows
                    items={filtered.slice(0, limit)}
                    onOpen={openItem}
                  />
                  {filtered.length > limit && (
                    <button
                      className="quiet-button load-more"
                      onClick={() => setLimit((n) => n + 30)}
                    >
                      Show 30 more
                    </button>
                  )}
                </>
              ) : (
                <div className="empty-state">
                  <h2>
                    {query
                      ? "No matching knowledge"
                      : "Nothing on this shelf yet"}
                  </h2>
                  <p>
                    {query
                      ? "Try a shorter word, a topic, or an item title."
                      : "Items on other shelves remain available in All knowledge."}
                  </p>
                  <button
                    className="quiet-button"
                    onClick={() => navigate("library")}
                  >
                    Browse all knowledge
                  </button>
                </div>
              )}
            </section>
          )}
          <footer className="desk-footer">
            <span>Prototype · sample knowledge</span>
            <button
              className="quiet-button"
              onClick={(e) => open({ kind: "settings" }, e.currentTarget)}
            >
              Example collection & appearance
            </button>
          </footer>
        </main>
      </div>
      <div
        className="toast-area"
        role="status"
        aria-live="polite"
        aria-atomic="true"
      >
        {(toast || undo) && (
          <div className="toast">
            <span>{undo ? undoMessage : toast}</span>
            {undo && (
              <button
                onClick={() => {
                  setState((s) => ({
                    ...s,
                    groups: undo.groups,
                    focused: undo.focused,
                  }));
                  setUndo(null);
                  announce("Change undone");
                }}
              >
                Undo
              </button>
            )}
          </div>
        )}
      </div>
      {overlay && (
        <Dialog
          title={overlayTitle}
          opener={opener.current}
          onClose={() => {
            setOverlay(null);
            setHistory([]);
          }}
          wide={overlay.kind === "reader"}
        >
          {overlay.kind === "reader" &&
            (current ? (
              readingState === "ready" ? (
                <Reader
                  key={current.id}
                  item={current}
                  items={items}
                  scrollPosition={readerPosition}
                  announce={announce}
                  canBack={history.length > 0}
                  related={(id, scroll) => {
                    setHistory((h) => [...h, { id: current.id, scroll }]);
                    setReaderPosition(0);
                    setOverlay({ kind: "reader", id });
                    requestAnimationFrame(() =>
                      document
                        .getElementById("dialog-title")
                        ?.focus({ preventScroll: true }),
                    );
                  }}
                  onBack={() => {
                    const previous = history[history.length - 1];
                    if (!previous) return;
                    setReaderPosition(previous.scroll);
                    setHistory((h) => h.slice(0, -1));
                    setOverlay({ kind: "reader", id: previous.id });
                    requestAnimationFrame(() =>
                      document
                        .getElementById("dialog-title")
                        ?.focus({ preventScroll: true }),
                    );
                  }}
                />
              ) : (
                <div className="modal-body reading-status">
                  {readingState === "loading" ? (
                    <>
                      <div className="skeleton" aria-hidden="true">
                        <span />
                        <span />
                        <span />
                      </div>
                      <p role="status">Opening saved knowledge…</p>
                      <button
                        className="quiet-button accent"
                        onClick={() => setReadingState("ready")}
                      >
                        Finish sample load
                      </button>
                    </>
                  ) : (
                    <>
                      <h3>This item could not be opened</h3>
                      <p>
                        Your desk and group are still here. Try opening the
                        sample again.
                      </p>
                      <button
                        className="primary-button"
                        onClick={() => setReadingState("ready")}
                      >
                        Try again
                      </button>
                    </>
                  )}
                </div>
              )
            ) : (
              <div className="modal-body">
                <p>
                  This sample item is no longer available. Close this view to
                  return to your desk.
                </p>
              </div>
            ))}
          {overlay.kind === "edit" && (
            <GroupEditor group={selectedGroup} items={items} onSave={save} />
          )}
          {overlay.kind === "group" && selectedGroup && (
            <div className="modal-body options-body">
              <p className="muted" role="status">
                {toast ||
                  selectedGroup.description ||
                  "A context you chose to keep together."}
              </p>
              <button
                className="option-action"
                onClick={() => focusGroup(selectedGroup)}
              >
                <Focus size={18} />
                {state.focused.includes(selectedGroup.id)
                  ? "Remove from Focus"
                  : "Add to Focus"}
                {state.focused.includes(selectedGroup.id) && (
                  <Check size={17} />
                )}
              </button>
              <button
                className="option-action"
                onClick={() =>
                  setOverlay({ kind: "edit", groupId: selectedGroup.id })
                }
              >
                Edit name & items
              </button>
              <button
                className="option-action"
                onClick={() => {
                  document
                    .querySelector<HTMLDialogElement>("dialog[open]")
                    ?.close();
                  setArranging(true);
                }}
              >
                Arrange groups
              </button>
              <button
                className="option-action remove-action"
                onClick={() => {
                  updateOrganization(
                    (s) => ({
                      ...s,
                      groups: s.groups.filter((g) => g.id !== selectedGroup.id),
                      focused: s.focused.filter(
                        (id) => id !== selectedGroup.id,
                      ),
                    }),
                    `${selectedGroup.title} removed. Its items are still in the library.`,
                  );
                  document
                    .querySelector<HTMLDialogElement>("dialog[open]")
                    ?.close();
                }}
              >
                Remove group · keep its items
              </button>
            </div>
          )}
          {overlay.kind === "settings" && (
            <div className="modal-body settings-body">
              <p>
                This is an isolated prototype. Knowledge is illustrative;
                organization changes stay in this browser.
              </p>
              <fieldset>
                <legend>Example collection</legend>
                <div className="dataset-options">
                  {(["empty", "sparse", "rich"] as Dataset[]).map((d) => (
                    <label key={d}>
                      <input
                        type="radio"
                        name="dataset"
                        checked={state.dataset === d}
                        onChange={() => changeDataset(d)}
                      />
                      <span>
                        {d === "empty"
                          ? "Empty"
                          : d === "sparse"
                            ? "A few saved things"
                            : "A larger library"}
                        <small>
                          {d === "empty"
                            ? "Start without saved knowledge"
                            : d === "sparse"
                              ? "Five items in one mixed group"
                              : "Mixed groups, a long thread, and 3,000 items"}
                        </small>
                      </span>
                    </label>
                  ))}
                </div>
              </fieldset>
              <fieldset>
                <legend>Appearance</legend>
                <div className="theme-options">
                  {(["light", "dark"] as const).map((t) => (
                    <label key={t}>
                      <input
                        type="radio"
                        name="theme"
                        checked={state.theme === t}
                        onChange={() => setState((s) => ({ ...s, theme: t }))}
                      />
                      {t === "light" ? "Light" : "Dark"}
                    </label>
                  ))}
                </div>
              </fieldset>
              <fieldset>
                <legend>Item loading example</legend>
                <div className="theme-options">
                  {(["ready", "loading", "error"] as const).map((mode) => (
                    <label key={mode}>
                      <input
                        type="radio"
                        name="readingState"
                        checked={readingState === mode}
                        onChange={() => setReadingState(mode)}
                      />
                      {mode === "ready"
                        ? "Ready"
                        : mode === "loading"
                          ? "Loading"
                          : "Error"}
                    </label>
                  ))}
                </div>
              </fieldset>
              <fieldset>
                <legend>Missing item example</legend>
                <button
                  className="quiet-button"
                  onClick={() => {
                    setOverlay({ kind: "reader", id: "missing-example" });
                  }}
                >
                  Open an unavailable item
                </button>
              </fieldset>
              <button
                className="quiet-button remove-action"
                onClick={() => changeDataset(state.dataset)}
              >
                Reset this example collection
              </button>
              <p className="muted">
                Your production knowledge, shelves, and settings are never
                accessed here.
              </p>
            </div>
          )}
          {overlay.kind === "capture" && (
            <div className="modal-body">
              <p>
                Capture stays in the production app. This prototype does not
                send links or files anywhere.
              </p>
              <p>
                You can explore saved example knowledge and organize it into
                groups.
              </p>
              <button
                className="primary-button"
                onClick={() => {
                  document
                    .querySelector<HTMLDialogElement>("dialog[open]")
                    ?.close();
                  navigate("library");
                }}
              >
                Browse sample knowledge
              </button>
            </div>
          )}
        </Dialog>
      )}
    </>
  );
}
