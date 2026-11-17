import { useWindowVirtualizer } from "@tanstack/react-virtual";
import { Check, Copy, RotateCcw, Tag, Trash2, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { NoteRow } from "@/components/note-row";
import { Confirm, Pop, PopContent, PopTrigger } from "@/components/overlay";
import { useToast } from "@/components/toast";
import { Button, Chip, EmptyState, ErrorState, Input, PageHeader, Skeleton } from "@/components/ui";
import { useCapture } from "@/app/capture";
import { useHotkeys } from "@/lib/hotkeys";
import { cleanTitle, dayKey, dayLabel, plural } from "@/lib/format";
import { useDeleteItem, useDuplicates, useLibrary, useReprocess, useTopics } from "@/lib/queries";
import type { LibraryItem } from "@/lib/schemas";
import { cn } from "@/lib/utils";

type Row = { kind: "day"; key: string; label: string } | { kind: "item"; item: LibraryItem };

const TYPE_NAME: Record<string, string> = {
  note: "Notes",
  url: "Links",
  web: "Articles",
  article: "Articles",
  pdf: "PDFs",
  video: "Videos",
  audio: "Audio",
  image: "Images",
};

export function Library() {
  const [params, setParams] = useSearchParams();
  const type = params.get("type") ?? undefined;
  const topic = params.get("topic") ?? undefined;
  const view = params.get("view") === "duplicates" ? "duplicates" : "all";
  const set = (k: string, v?: string) =>
    setParams(
      (p) => {
        const n = new URLSearchParams(p);
        if (v) n.set(k, v);
        else n.delete(k);
        return n;
      },
      { replace: true },
    );

  const lib = useLibrary({ type, topic }, false);
  const first = lib.data?.pages[0];
  const items = useMemo(() => lib.data?.pages.flatMap((p) => p.items) ?? [], [lib.data]);
  const total = first?.total ?? 0;
  const types = first?.types ?? {};

  useEffect(() => {
    document.title = "Library · Pith";
  }, []);

  return (
    <div className="enter">
      <PageHeader
        title="Library"
        sub={lib.isSuccess ? `${plural(total, "note")}${type || topic ? " match" : ""} · newest first` : "Everything Pith has read for you"}
        actions={
          <div role="group" aria-label="View" className="flex rounded-md border border-line p-0.5">
            {(["all", "duplicates"] as const).map((v) => (
              <button
                key={v}
                type="button"
                aria-pressed={view === v}
                onClick={() => set("view", v === "all" ? undefined : v)}
                className={cn(
                  "h-7 rounded px-2.5 text-[13px] font-medium",
                  view === v ? "bg-raise text-ink shadow-[0_0_0_1px_var(--line)]" : "text-mut hover:text-ink",
                )}
              >
                {v === "all" ? "All notes" : "Duplicates"}
              </button>
            ))}
          </div>
        }
      />
      {view === "duplicates" ? (
        <DuplicatesView />
      ) : (
        <>
          <Filters
            types={types}
            type={type}
            topic={topic}
            onType={(v) => set("type", v)}
            onTopic={(v) => set("topic", v)}
            onClear={() =>
              setParams(
                (p) => {
                  const n = new URLSearchParams(p);
                  n.delete("type");
                  n.delete("topic");
                  return n;
                },
                { replace: true },
              )
            }
          />
          {lib.isPending ? (
            <ListSkeleton />
          ) : lib.isError ? (
            <ErrorState error={lib.error} retry={() => void lib.refetch()} />
          ) : items.length === 0 ? (
            <LibraryEmpty filtered={!!(type || topic)} clear={() => setParams({}, { replace: true })} />
          ) : (
            <NoteList
              items={items}
              hasMore={!!lib.hasNextPage}
              loadingMore={lib.isFetchingNextPage}
              loadMore={() => void lib.fetchNextPage()}
            />
          )}
        </>
      )}
    </div>
  );
}

function LibraryEmpty({ filtered, clear }: { filtered: boolean; clear: () => void }) {
  const { open } = useCapture();
  return filtered ? (
    <EmptyState title="Nothing matches those filters" action={<Button onClick={clear}>Clear filters</Button>}>
      Try a different type or topic.
    </EmptyState>
  ) : (
    <EmptyState
      title="Your library is empty"
      action={
        <Button variant="primary" onClick={open}>
          Save something
        </Button>
      }
    >
      Notes appear here once Pith has read what you saved. Drop a file anywhere on the page, press <kbd className="font-sans">n</kbd>, or
      use the drop folder.
    </EmptyState>
  );
}

function ListSkeleton() {
  return (
    <div aria-busy className="space-y-px">
      {Array.from({ length: 8 }, (_, i) => (
        <div key={i} className="border-b border-hair px-4 py-3">
          <Skeleton className="h-4 w-2/5" />
          <Skeleton className="mt-2 h-3.5 w-4/5" />
          <Skeleton className="mt-2 h-3 w-1/4" />
        </div>
      ))}
    </div>
  );
}

function Filters({
  types,
  type,
  topic,
  onType,
  onTopic,
  onClear,
}: {
  types: Record<string, number>;
  type?: string;
  topic?: string;
  onType: (v?: string) => void;
  onTopic: (v?: string) => void;
  onClear: () => void;
}) {
  const topics = useTopics();
  const [q, setQ] = useState("");
  const [openTopics, setOpenTopics] = useState(false);
  const shown = (topics.data ?? []).filter((t) => t.name.toLowerCase().includes(q.trim().toLowerCase())).slice(0, 80);
  const typeEntries = Object.entries(types);
  return (
    <div className="mb-3 flex flex-wrap items-center gap-2">
      <div role="group" aria-label="Filter by type" className="flex flex-wrap gap-1.5">
        <FilterChip active={!type} onClick={() => onType(undefined)}>
          All
        </FilterChip>
        {typeEntries.map(([t, n]) => (
          <FilterChip key={t} active={type === t} onClick={() => onType(type === t ? undefined : t)}>
            {TYPE_NAME[t] ?? t} <span className="text-mut tabular-nums">{n.toLocaleString()}</span>
          </FilterChip>
        ))}
      </div>
      <Pop open={openTopics} onOpenChange={setOpenTopics}>
        <PopTrigger asChild>
          <Button size="sm" variant={topic ? "primary" : "secondary"} aria-label="Filter by topic">
            <Tag className="size-3.5" aria-hidden /> {topic ?? "Topics"}
          </Button>
        </PopTrigger>
        <PopContent className="w-64">
          <Input
            aria-label="Search topics"
            placeholder="Search topics"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            className="mb-2 h-8"
            // eslint-disable-next-line jsx-a11y/no-autofocus -- the popover opens for this search field
            autoFocus
          />
          <ul className="max-h-64 overflow-y-auto">
            {topics.isPending && <li className="px-2 py-1.5 text-[13px] text-mut">Loading…</li>}
            {topics.isSuccess && shown.length === 0 && (
              <li className="px-2 py-1.5 text-[13px] text-mut">
                {(topics.data?.length ?? 0) === 0 ? "No topics yet. Pith assigns them as it reads." : "No topic matches."}
              </li>
            )}
            {shown.map((t) => (
              <li key={t.name}>
                <button
                  type="button"
                  className="flex w-full items-center justify-between rounded-md px-2 py-1.5 text-left text-[13.5px] hover:bg-panel"
                  onClick={() => (onTopic(topic === t.name ? undefined : t.name), setOpenTopics(false))}
                >
                  <span className="flex items-center gap-1.5 truncate">
                    {topic === t.name && <Check className="size-3.5 text-acc" aria-hidden />}
                    {t.name}
                  </span>
                  <span className="text-mut tabular-nums">{t.n}</span>
                </button>
              </li>
            ))}
          </ul>
        </PopContent>
      </Pop>
      {(type || topic) && (
        <Button size="sm" variant="ghost" onClick={onClear}>
          <X className="size-3.5" aria-hidden /> Clear
        </Button>
      )}
    </div>
  );
}

const FilterChip = ({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) => (
  <button
    type="button"
    aria-pressed={active}
    onClick={onClick}
    className={cn(
      "inline-flex h-7 items-center gap-1.5 rounded-full border px-3 text-[13px] font-medium transition-colors",
      active ? "border-ink bg-ink text-paper" : "border-line bg-raise text-soft hover:border-mut hover:text-ink",
    )}
  >
    {children}
  </button>
);

function NoteList({
  items,
  hasMore,
  loadingMore,
  loadMore,
}: {
  items: LibraryItem[];
  hasMore: boolean;
  loadingMore: boolean;
  loadMore: () => void;
}) {
  const nav = useNavigate();
  const toast = useToast();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [active, setActive] = useState(-1);
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const del = useDeleteItem();
  const re = useReprocess();
  const listRef = useRef<HTMLDivElement>(null);

  const rows = useMemo<Row[]>(() => {
    const out: Row[] = [];
    let last = "";
    for (const item of items) {
      const k = dayKey(item.created_at);
      if (k !== last) out.push({ kind: "day", key: k, label: dayLabel(item.created_at) });
      last = k;
      out.push({ kind: "item", item });
    }
    return out;
  }, [items]);

  const virt = useWindowVirtualizer({
    count: rows.length,
    estimateSize: (i) => (rows[i]?.kind === "day" ? 40 : 108),
    overscan: 8,
    scrollMargin: listRef.current?.offsetTop ?? 0,
    getItemKey: (i) => {
      const r = rows[i];
      return r ? (r.kind === "day" ? `d-${r.key}` : r.item.id) : i;
    },
  });
  const vItems = virt.getVirtualItems();
  const lastIdx = vItems.at(-1)?.index ?? 0;
  useEffect(() => {
    if (hasMore && !loadingMore && lastIdx >= rows.length - 10) loadMore();
  }, [lastIdx, rows.length, hasMore, loadingMore, loadMore]);

  const itemRowIdx = useMemo(() => rows.map((r, i) => (r.kind === "item" ? i : -1)).filter((i) => i >= 0), [rows]);
  const move = useCallback(
    (d: 1 | -1) => {
      const next = Math.min(items.length - 1, Math.max(0, active + d));
      setActive(next);
      const ri = itemRowIdx[next];
      if (ri !== undefined) virt.scrollToIndex(ri, { align: "auto" });
    },
    [active, items.length, itemRowIdx, virt],
  );
  useHotkeys({
    j: () => move(1),
    k: () => move(-1),
    Enter: () => {
      const it = items[active];
      if (it && !(document.activeElement as HTMLElement | null)?.closest("a,button")) nav(`/note/${it.id}`);
    },
    x: () => {
      const it = items[active];
      if (it) toggle(it.id, !selected.has(it.id));
    },
    Escape: () => setSelected(new Set()),
  });

  const toggle = (id: string, on: boolean) =>
    setSelected((s) => {
      const n = new Set(s);
      if (on) n.add(id);
      else n.delete(id);
      return n;
    });

  const run = async (fn: (id: string) => Promise<unknown>, done: string) => {
    setBusy(true);
    const ids = [...selected];
    const res = await Promise.allSettled(ids.map(fn));
    const bad = res.filter((r) => r.status === "rejected").length;
    setBusy(false);
    setConfirm(false);
    setSelected(new Set());
    toast(bad ? `${plural(ids.length - bad, "note")} ${done}; ${bad} failed.` : `${plural(ids.length, "note")} ${done}.`, { bad: !!bad });
  };

  const copySelected = async () => {
    const lines = items.filter((i) => selected.has(i.id)).map((i) => `- ${cleanTitle(i.title)}${i.url ? ` — ${i.url}` : ""}`);
    try {
      await navigator.clipboard.writeText(lines.join("\n"));
      toast(`Copied ${plural(lines.length, "title")}.`);
    } catch {
      toast("Copying is blocked by the browser.", { bad: true });
    }
  };

  return (
    <div>
      {selected.size > 0 && (
        <div
          role="toolbar"
          aria-label="Bulk actions"
          className="sticky top-12 z-20 mb-2 flex flex-wrap items-center gap-2 rounded-lg border border-acc/40 bg-acc-tint px-3 py-2 md:top-2"
        >
          <span className="mr-2 font-medium tabular-nums">{selected.size} selected</span>
          <Button size="sm" onClick={() => void copySelected()}>
            <Copy className="size-3.5" aria-hidden /> Copy list
          </Button>
          <Button size="sm" disabled={busy} onClick={() => void run((id) => re.mutateAsync(id), "queued to read again")}>
            <RotateCcw className="size-3.5" aria-hidden /> Read again
          </Button>
          <Button size="sm" variant="danger" onClick={() => setConfirm(true)}>
            <Trash2 className="size-3.5" aria-hidden /> Delete
          </Button>
          <Button size="sm" variant="ghost" className="ml-auto" onClick={() => setSelected(new Set())}>
            Clear selection
          </Button>
        </div>
      )}
      <div ref={listRef} className="overflow-hidden rounded-xl border border-line bg-raise" role="list" aria-label="Notes">
        <div style={{ height: virt.getTotalSize(), position: "relative" }}>
          {vItems.map((v) => {
            const r = rows[v.index];
            if (!r) return null;
            return (
              <div
                key={v.key}
                data-index={v.index}
                ref={virt.measureElement}
                role="listitem"
                style={{
                  position: "absolute",
                  top: 0,
                  left: 0,
                  width: "100%",
                  transform: `translateY(${v.start - virt.options.scrollMargin}px)`,
                }}
              >
                {r.kind === "day" ? (
                  <h2 className="border-b border-hair bg-panel/60 px-4 py-2 text-[12px] font-semibold tracking-[0.06em] text-mut uppercase">
                    {r.label}
                  </h2>
                ) : (
                  <NoteRow
                    item={r.item}
                    selected={selected.has(r.item.id)}
                    selecting={selected.size > 0}
                    onSelect={toggle}
                    active={items[active]?.id === r.item.id}
                  />
                )}
              </div>
            );
          })}
        </div>
      </div>
      <p className="py-5 text-center text-[13px] text-mut" aria-live="polite">
        {loadingMore ? "Loading more…" : hasMore ? "" : `That is everything · ${plural(items.length, "note")}`}
      </p>
      <Confirm
        open={confirm}
        onOpenChange={setConfirm}
        title={`Delete ${plural(selected.size, "note")}?`}
        body="They disappear from the library and search. The original files are kept."
        confirmLabel="Delete"
        busy={busy}
        onConfirm={() => void run((id) => del.mutateAsync(id), "deleted")}
      />
    </div>
  );
}

function DuplicatesView() {
  const d = useDuplicates(true);
  const del = useDeleteItem();
  const toast = useToast();
  const [target, setTarget] = useState<{ id: string; title: string } | null>(null);
  if (d.isPending) return <ListSkeleton />;
  if (d.isError) return <ErrorState error={d.error} retry={() => void d.refetch()} />;
  if (d.data.length === 0)
    return (
      <EmptyState title="No near-duplicates">
        Pith compares every new note with what you already saved and lists very similar pairs here.
      </EmptyState>
    );
  return (
    <div>
      <p className="mb-3 text-[13.5px] text-mut">
        {plural(d.data.length, "pair")} that read almost the same. Open both, then delete the one you do not need.
      </p>
      <ul className="divide-y divide-hair overflow-hidden rounded-xl border border-line bg-raise">
        {d.data.map((p) => (
          <li key={`${p.a.id}-${p.b.id}`} className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3">
            <Chip tone="warn">{Math.round(p.score * 100)}% alike</Chip>
            {[p.a, p.b].map((x) => (
              <span key={x.id} className="flex min-w-0 flex-1 basis-56 items-center gap-2">
                <Link to={`/note/${x.id}`} className="truncate font-medium hover:text-acc">
                  {cleanTitle(x.title)}
                </Link>
                <Button size="iconSm" variant="ghost" aria-label={`Delete ${cleanTitle(x.title)}`} onClick={() => setTarget(x)}>
                  <Trash2 className="size-3.5" />
                </Button>
              </span>
            ))}
          </li>
        ))}
      </ul>
      <Confirm
        open={!!target}
        onOpenChange={(o) => !o && setTarget(null)}
        title="Delete this note?"
        body={target ? cleanTitle(target.title) : ""}
        confirmLabel="Delete"
        busy={del.isPending}
        onConfirm={() =>
          target &&
          del.mutate(target.id, {
            onSuccess: () => (toast("Deleted."), setTarget(null)),
            onError: () => toast("Could not delete.", { bad: true }),
          })
        }
      />
    </div>
  );
}
