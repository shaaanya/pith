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
  Layers,
  MoreHorizontal,
  Plus,
  Settings2,
  Terminal,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { Link } from "react-router";
import { DeskDialog } from "@/components/desk-dialog";
import { Button, ErrorState, Skeleton } from "@/components/ui";
import { useToast } from "@/components/toast";
import { useCapture } from "@/app/capture";
import { ApiError } from "@/lib/api";
import { cleanTitle } from "@/lib/format";
import { read, write } from "@/lib/local";
import { useAppState, useDesk, useLibrary, useSaveDesk, useSearch } from "@/lib/queries";
import type { Desk as DeskState, DeskGroup, DeskItem } from "@/lib/schemas";
import { ReaderContent } from "./reader";
import "./desk.css";

type Workspace = "focus" | "overview";
type View = { workspace: Workspace; expanded: Record<Workspace, string[]> };
const VIEW_KEY = "pith.desk.view.v1";
function initialView(): View {
  try {
    const v = JSON.parse(read(VIEW_KEY) ?? "null");
    if (
      v &&
      ["focus", "overview"].includes(v.workspace) &&
      [v.expanded?.focus, v.expanded?.overview].every((x) => Array.isArray(x) && x.every((id: unknown) => typeof id === "string"))
    )
      return v;
  } catch {
    /* blocked or old preferences: use defaults */
  }
  return { workspace: "overview", expanded: { focus: [], overview: [] } };
}
const icons: Record<string, typeof Bookmark> = {
  bookmark: Bookmark,
  database: Database,
  terminal: Terminal,
  book: BookOpen,
  compass: Compass,
  layers: Layers,
};
type Overlay =
  | { kind: "edit"; group?: DeskGroup; base?: DeskState }
  | { kind: "options"; group: DeskGroup; base?: DeskState }
  | { kind: "reader"; id: string };

export function Desk() {
  const desk = useDesk();
  const save = useSaveDesk();
  const state = useAppState();
  const working = (state.data?.counts.pending ?? 0) + (state.data?.counts.processing ?? 0) + (state.data?.counts.new ?? 0);
  const attention = (state.data?.counts.failed ?? 0) + (state.data?.counts.needs_clarification ?? 0);
  const recent = useLibrary({}, working > 0);
  const capture = useCapture();
  const toast = useToast();
  const [view, setView] = useState(initialView);
  const [arranging, setArranging] = useState(false);
  const [shown, setShown] = useState<Record<string, number>>({});
  const [overlay, setOverlay] = useState<Overlay | null>(null);
  const [undo, setUndo] = useState<DeskState | null>(null);
  const [message, setMessage] = useState("");
  const opener = useRef<HTMLElement | null>(null);
  const saving = useRef(false);
  const pageScroll = useRef<Record<Workspace, number>>({ focus: 0, overview: 0 });
  const [readerHistory, setReaderHistory] = useState<{ id: string; scroll: number }[]>([]);
  const [readerScroll, setReaderScroll] = useState(0);
  const readerBody = useRef<HTMLDivElement>(null);
  const groups = desk.data?.groups ?? [];
  const active = groups.filter((g) => view.workspace === "overview" || g.focused);

  useEffect(() => {
    write(VIEW_KEY, JSON.stringify(view));
  }, [view]);
  useEffect(() => {
    document.title = "Your desk · Pith";
  }, []);
  useEffect(() => {
    const frame = requestAnimationFrame(() => {
      if (readerBody.current) readerBody.current.scrollTop = readerScroll;
    });
    return () => cancelAnimationFrame(frame);
  }, [overlay, readerScroll]);

  function open(next: Overlay, invoker: HTMLElement) {
    opener.current = invoker;
    setReaderHistory([]);
    setReaderScroll(0);
    setOverlay(next.kind === "reader" ? next : { ...next, base: desk.data });
  }
  function close() {
    setOverlay(null);
    document.title = "Your desk · Pith";
  }
  function workspace(next: Workspace) {
    if (view.workspace === next) return;
    pageScroll.current[view.workspace] = window.scrollY;
    setView((v) => ({ ...v, workspace: next }));
    setArranging(false);
    requestAnimationFrame(() => window.scrollTo({ top: pageScroll.current[next], behavior: "instant" }));
  }
  async function organize(next: DeskGroup[], announcement: string, keepUndo = true, base = desk.data) {
    if (!base || saving.current) return false;
    saving.current = true;
    try {
      const result = await save.mutateAsync({ revision: base.revision, groups: next });
      if (keepUndo) setUndo({ revision: result.revision, groups: base.groups });
      else setUndo(null);
      setMessage(announcement);
      toast(announcement);
      return true;
    } catch {
      return false;
    } finally {
      saving.current = false;
    }
  }
  function move(group: DeskGroup, direction: -1 | 1) {
    const index = active.findIndex((g) => g.id === group.id);
    const neighbor = active[index + direction];
    if (!neighbor) return;
    const next = [...groups];
    const a = next.findIndex((g) => g.id === group.id),
      b = next.findIndex((g) => g.id === neighbor.id);
    if (a < 0 || b < 0) return;
    [next[a], next[b]] = [next[b]!, next[a]!];
    void organize(next, `${group.title} moved ${direction < 0 ? "up" : "down"}.`);
  }
  async function saveGroup(group: DeskGroup) {
    const base = overlay?.kind === "edit" ? overlay.base : undefined;
    if (!base) return;
    const next = base.groups.some((g) => g.id === group.id)
      ? base.groups.map((g) => (g.id === group.id ? group : g))
      : [...base.groups, group];
    if (await organize(next, `${group.title} saved.`, true, base)) close();
  }
  const conflict = save.error instanceof ApiError && save.error.status === 409;
  const errorMessage = save.error ? (save.error instanceof Error ? save.error.message : "Could not save your desk.") : "";
  const error = save.isError && (
    <div role="alert" className="desk-error">
      <p>{errorMessage}</p>
      {conflict && <p>Your changes have not been saved. Load the latest desk, then apply them again.</p>}
      {conflict && (
        <button
          className="desk-quiet"
          onClick={() => {
            close();
            setUndo(null);
            save.reset();
            void desk.refetch();
          }}
        >
          Load latest desk
        </button>
      )}
    </div>
  );
  const title =
    overlay?.kind === "edit"
      ? overlay.group
        ? "Edit group"
        : "New group"
      : overlay?.kind === "options"
        ? overlay.group.title
        : "Saved knowledge";

  if (desk.isPending)
    return (
      <div aria-busy="true">
        <Skeleton className="h-10 w-72" />
        <Skeleton className="mt-12 h-24 w-full" />
      </div>
    );
  if (desk.isError) return <ErrorState error={desk.error} retry={() => void desk.refetch()} />;

  return (
    <div className="pith-desk">
      <header className="desk-page-header">
        <div>
          <h1 id="page-title" tabIndex={-1}>
            Your Working Desk
          </h1>
          <p>
            {view.workspace === "focus"
              ? "A few chosen contexts, kept within reach."
              : "Your contexts, ready when you are. Open a group to follow a thread."}
          </p>
        </div>
        <div className="desk-controls">
          <div className="desk-workspace" role="group" aria-label="Workspace">
            <button aria-pressed={view.workspace === "focus"} onClick={() => workspace("focus")}>
              <Focus size={15} aria-hidden />
              Focus {groups.some((g) => g.focused) && <span>{groups.filter((g) => g.focused).length}</span>}
            </button>
            <button aria-pressed={view.workspace === "overview"} onClick={() => workspace("overview")}>
              Overview
            </button>
          </div>
          <div className="desk-utilities">
            <button className="desk-quiet" aria-pressed={arranging} onClick={() => setArranging((v) => !v)}>
              {arranging ? <Check size={16} aria-hidden /> : <Settings2 size={16} aria-hidden />}
              {arranging ? "Finish arranging" : "Arrange"}
            </button>
            <button className="desk-quiet desk-accent" onClick={(e) => open({ kind: "edit" }, e.currentTarget)}>
              <Plus size={16} aria-hidden />
              New group
            </button>
          </div>
        </div>
      </header>
      {!overlay && error}
      {arranging && (
        <p className="desk-arrange-hint">
          Move groups into an order that feels familiar. Your changes are saved in Pith; you can undo the last change.
        </p>
      )}
      {active.length === 0 ? (
        <div className="desk-empty">
          <Bookmark size={24} aria-hidden />
          <h2>{view.workspace === "focus" ? "Choose what stays close" : "A little room for what matters"}</h2>
          <p>
            {view.workspace === "focus"
              ? "Add a group to Focus from its group options. Your other groups will still be in Overview."
              : "Make a group around a question, a weekend, or something you are exploring."}
          </p>
          <div className="desk-empty-actions">
            {view.workspace === "focus" ? (
              <button className="desk-primary" onClick={() => workspace("overview")}>
                Go to Overview
              </button>
            ) : (
              <button className="desk-primary" onClick={(e) => open({ kind: "edit" }, e.currentTarget)}>
                Create a group
              </button>
            )}
            <Link className="desk-quiet" to="/library">
              All knowledge
            </Link>
            <button className="desk-quiet" onClick={() => capture.open()}>
              Save something
            </button>
          </div>
        </div>
      ) : (
        <div className="desk-group-grid">
          {active.map((group, index) => {
            const expanded = view.expanded[view.workspace].includes(group.id);
            const Icon = icons[group.icon] ?? Bookmark;
            const count = shown[group.id] ?? 5;
            return (
              <section className={`desk-group${expanded ? " expanded" : ""}`} key={group.id} data-group-id={group.id}>
                <div className="desk-group-heading">
                  <h2>
                    <button
                      className="desk-group-trigger"
                      id={`trigger-${group.id}`}
                      aria-expanded={expanded}
                      aria-controls={`panel-${group.id}`}
                      onClick={() =>
                        setView((v) => ({
                          ...v,
                          expanded: {
                            ...v.expanded,
                            [v.workspace]: expanded
                              ? v.expanded[v.workspace].filter((id) => id !== group.id)
                              : [...v.expanded[v.workspace], group.id],
                          },
                        }))
                      }
                    >
                      <Icon className="desk-group-symbol" size={18} aria-hidden />
                      <span className="desk-group-label">
                        <span>{group.title}</span>
                        {group.description && <small>{group.description}</small>}
                      </span>
                      <span className="desk-group-count">
                        {group.items.length}
                        <span className="sr-only"> items</span>
                      </span>
                      <ChevronDown className="desk-disclosure" size={17} aria-hidden />
                    </button>
                  </h2>
                  <button
                    className="desk-icon"
                    aria-label={`Options for ${group.title}`}
                    onClick={(e) => open({ kind: "options", group }, e.currentTarget)}
                  >
                    <MoreHorizontal size={18} aria-hidden />
                  </button>
                </div>
                {arranging && (
                  <div className="desk-arrange-tools">
                    <button
                      className="desk-quiet"
                      aria-label={`Move ${group.title} up`}
                      disabled={save.isPending || index === 0}
                      onClick={() => move(group, -1)}
                    >
                      <ArrowUp size={15} aria-hidden />
                      Move up
                    </button>
                    <button
                      className="desk-quiet"
                      aria-label={`Move ${group.title} down`}
                      disabled={save.isPending || index === active.length - 1}
                      onClick={() => move(group, 1)}
                    >
                      <ArrowDown size={15} aria-hidden />
                      Move down
                    </button>
                  </div>
                )}
                <div id={`panel-${group.id}`} hidden={!expanded} className="desk-group-panel">
                  {group.items.length ? (
                    <ItemRows items={group.items.slice(0, count)} onOpen={(id, invoker) => open({ kind: "reader", id }, invoker)} />
                  ) : (
                    <div className="desk-empty-group">
                      <p>Nothing in this group yet.</p>
                      <button className="desk-quiet desk-accent" onClick={(e) => open({ kind: "edit", group }, e.currentTarget)}>
                        Choose items
                      </button>
                    </div>
                  )}
                  {group.items.length > 5 && (
                    <div className="desk-continuation">
                      <span>
                        {Math.min(count, group.items.length)} of {group.items.length}
                      </span>
                      {count < group.items.length ? (
                        <button className="desk-quiet desk-accent" onClick={() => setShown((s) => ({ ...s, [group.id]: count + 10 }))}>
                          Show more
                        </button>
                      ) : (
                        <button className="desk-quiet" onClick={() => setShown((s) => ({ ...s, [group.id]: 5 }))}>
                          Show fewer
                        </button>
                      )}
                    </div>
                  )}
                </div>
              </section>
            );
          })}
        </div>
      )}
      <footer className="desk-footer">
        <span>
          {groups.length} {groups.length === 1 ? "context" : "contexts"} · Organized by you
        </span>
        {undo && (
          <button
            className="desk-quiet desk-accent"
            disabled={save.isPending || conflict}
            onClick={() => void organize(undo.groups, "Last organization change undone.", false, undo)}
          >
            Undo last change
          </button>
        )}
      </footer>
      <span className="sr-only" role="status">
        {message}
      </span>
      <div className="desk-updates">
        {(attention > 0 || working > 0) && (
          <p>
            <Link to={attention ? "/inbox?show=attention" : "/inbox"}>
              {attention > 0
                ? `${attention} ${attention === 1 ? "capture needs" : "captures need"} your attention`
                : `Reading ${working} ${working === 1 ? "capture" : "captures"}`}
              <ChevronRight size={14} aria-hidden />
            </Link>
          </p>
        )}
        {recent.isError && (
          <p>
            Recent captures could not load.{" "}
            <button className="desk-quiet" onClick={() => void recent.refetch()}>
              Try again
            </button>
          </p>
        )}
        {!!recent.data?.pages[0]?.items.length && (
          <details>
            <summary>
              Recently saved <span>· {recent.data.pages[0].total} notes in your library</span>
            </summary>
            <ItemRows items={recent.data.pages[0].items.slice(0, 5)} onOpen={(id, invoker) => open({ kind: "reader", id }, invoker)} />
            <Link className="desk-quiet desk-accent" to="/library">
              All knowledge
            </Link>
          </details>
        )}
      </div>
      {overlay && (
        <DeskDialog title={title} opener={opener.current} onClose={close} wide={overlay.kind === "reader"}>
          {overlay.kind !== "reader" && error}
          {overlay.kind === "edit" && (
            <GroupEditor group={overlay.group} busy={save.isPending || conflict} onSave={saveGroup} onCancel={close} />
          )}
          {overlay.kind === "options" && (
            <div className="desk-options">
              <p>Keep this context close, or change what belongs here.</p>
              <button
                className="desk-option"
                disabled={save.isPending || conflict}
                onClick={() =>
                  void organize(
                    (overlay.base?.groups ?? []).map((g) => (g.id === overlay.group.id ? { ...g, focused: !g.focused } : g)),
                    `${overlay.group.title} ${overlay.group.focused ? "removed from" : "added to"} Focus.`,
                    true,
                    overlay.base,
                  ).then((ok) => {
                    if (ok) close();
                  })
                }
              >
                <Focus size={17} aria-hidden />
                {overlay.group.focused ? "Remove from Focus" : "Add to Focus"}
              </button>
              <button className="desk-option" onClick={() => setOverlay({ kind: "edit", group: overlay.group, base: overlay.base })}>
                <Settings2 size={17} aria-hidden />
                Edit group
              </button>
              <button
                className="desk-option desk-accent"
                disabled={save.isPending || conflict}
                onClick={() =>
                  void organize(
                    (overlay.base?.groups ?? []).filter((g) => g.id !== overlay.group.id),
                    `${overlay.group.title} removed. Its knowledge is still in your library.`,
                    true,
                    overlay.base,
                  ).then((ok) => {
                    if (ok) close();
                  })
                }
              >
                Remove group
              </button>
              <p className="desk-muted">Removing a group keeps all its knowledge in your library.</p>
            </div>
          )}
          {overlay.kind === "reader" && (
            <div className="desk-reader-body" ref={readerBody}>
              <ReaderContent
                key={overlay.id}
                id={overlay.id}
                embedded
                onBack={() => {
                  const prev = readerHistory.at(-1);
                  if (!prev) {
                    close();
                    return;
                  }
                  setReaderHistory((h) => h.slice(0, -1));
                  setReaderScroll(prev.scroll);
                  setOverlay({ kind: "reader", id: prev.id });
                }}
                onNavigateRelated={(id) => {
                  setReaderHistory((h) => [...h, { id: overlay.id, scroll: readerBody.current?.scrollTop ?? 0 }]);
                  setReaderScroll(0);
                  setOverlay({ kind: "reader", id });
                }}
              />
            </div>
          )}
        </DeskDialog>
      )}
    </div>
  );
}

function ItemRows({ items, onOpen }: { items: DeskItem[]; onOpen: (id: string, invoker: HTMLElement) => void }) {
  return (
    <ul className="desk-item-list">
      {items.map((item) => (
        <li key={item.id}>
          <button className="desk-item-row" onClick={(e) => onOpen(item.id, e.currentTarget)}>
            <span>{cleanTitle(item.title)}</span>
            <small>{item.type ?? item.kind}</small>
            <ChevronRight size={15} aria-hidden />
          </button>
        </li>
      ))}
    </ul>
  );
}

function GroupEditor({
  group,
  busy,
  onSave,
  onCancel,
}: {
  group?: DeskGroup;
  busy: boolean;
  onSave: (group: DeskGroup) => Promise<void>;
  onCancel: () => void;
}) {
  const [title, setTitle] = useState(group?.title ?? "");
  const [description, setDescription] = useState(group?.description ?? "");
  const [selected, setSelected] = useState(new Set(group?.item_ids ?? []));
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  const library = useLibrary({}, false);
  const search = useSearch(debounced, {});
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(query.trim()), 250);
    return () => clearTimeout(timer);
  }, [query]);
  const searching = debounced.length > 1;
  const candidates = useMemo(() => {
    const list: { id: string; title: string; type: string }[] = searching
      ? (search.data?.hits ?? []).flatMap((h) =>
          (h.note_id ?? (["note", "summary"].includes(h.kind) ? h.item_id : null))
            ? [{ id: (h.note_id ?? h.item_id)!, title: h.title, type: "note" }]
            : [],
        )
      : (library.data?.pages.flatMap((p) => p.items) ?? []).map((i) => ({ id: i.id, title: i.title, type: i.type ?? i.kind }));
    return [...new Map(list.map((i) => [i.id, i])).values()];
  }, [searching, search.data, library.data]);
  const currentQuery = searching ? search : library;
  const waitingForSearch = query.trim() !== debounced || (searching && (search.isFetching || search.isPlaceholderData));
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!title.trim() || busy) return;
    const item_ids = [
      ...(group?.item_ids ?? []).filter((id) => selected.has(id)),
      ...[...selected].filter((id) => !group?.item_ids.includes(id)),
    ];
    await onSave({
      id: group?.id ?? crypto.randomUUID(),
      title: title.trim(),
      description: description.trim(),
      icon: group?.icon ?? "bookmark",
      focused: group?.focused ?? false,
      item_ids,
      items: group?.items ?? [],
    });
  }
  return (
    <form className="desk-editor" onSubmit={(e) => void submit(e)}>
      <div className="desk-editor-body">
        <label htmlFor="desk-group-name">
          Group name
          <input
            id="desk-group-name"
            data-initial-focus
            required
            maxLength={80}
            autoComplete="off"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            disabled={busy}
          />
        </label>
        <label htmlFor="desk-group-description">
          A little context <span className="desk-muted">(optional)</span>
          <input
            id="desk-group-description"
            maxLength={140}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            disabled={busy}
          />
        </label>
        <fieldset disabled={busy}>
          <legend>Items in this group · {selected.size} selected</legend>
          <p className="desk-muted">Mix any kinds of knowledge. Removing an item here keeps it in your library.</p>
          {selected.size > 0 && (
            <details className="desk-selected">
              <summary>Selected items ({selected.size})</summary>
              {[...selected].map((id) => (
                <label className="desk-membership-row" key={id}>
                  <input type="checkbox" checked onChange={() => setSelected((old) => new Set([...old].filter((x) => x !== id)))} />
                  <span>
                    {group?.items.find((i) => i.id === id)?.title ?? candidates.find((i) => i.id === id)?.title ?? `Saved note ${id}`}
                  </span>
                </label>
              ))}
            </details>
          )}
          <label htmlFor="desk-find-items">
            Find items
            <input
              id="desk-find-items"
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search your saved knowledge"
            />
          </label>
          {currentQuery.isError && <ErrorState error={currentQuery.error} retry={() => void currentQuery.refetch()} />}
          {(currentQuery.isPending || waitingForSearch) && <p className="desk-muted">Loading saved knowledge…</p>}
          <div className="desk-membership-list">
            {(waitingForSearch ? [] : candidates).map((item) => (
              <label className="desk-membership-row" key={item.id}>
                <input
                  type="checkbox"
                  checked={selected.has(item.id)}
                  onChange={(e) =>
                    setSelected((old) => {
                      const next = new Set(old);
                      if (e.target.checked) next.add(item.id);
                      else next.delete(item.id);
                      return next;
                    })
                  }
                />
                <span>
                  {cleanTitle(item.title)}
                  <small>{item.type}</small>
                </span>
              </label>
            ))}
          </div>
          {!currentQuery.isPending && !waitingForSearch && candidates.length === 0 && (
            <p className="desk-muted">
              {searching ? "No matching saved knowledge. Try another word." : "No saved knowledge yet. Save a source to get started."}
            </p>
          )}
          {!searching && library.hasNextPage && (
            <Button disabled={library.isFetchingNextPage} onClick={() => void library.fetchNextPage()}>
              Load more saved knowledge
            </Button>
          )}
          {searching && <p className="desk-muted">Top matching saved notes. Refine your search to find another item.</p>}
        </fieldset>
      </div>
      <footer className="desk-editor-footer">
        <button type="button" className="desk-quiet" onClick={onCancel}>
          Cancel
        </button>
        <button className="desk-primary" type="submit" disabled={!title.trim() || busy}>
          {busy ? "Saving…" : "Save group"}
        </button>
      </footer>
    </form>
  );
}
