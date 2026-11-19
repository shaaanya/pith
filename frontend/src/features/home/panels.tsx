import { Paperclip, Search } from "lucide-react";
import { useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { Link, useNavigate } from "react-router";
import { useCapture } from "@/app/capture";
import { ShelfIcon } from "@/components/shelf-bits";
import { Button, Input, SectionTitle, Textarea } from "@/components/ui";
import { cleanTitle, dayLabel, when } from "@/lib/format";
import { isNew } from "@/lib/local";
import { useEntries, useTopics } from "@/lib/queries";
import type { Entry, LibraryItem, Resurfaced } from "@/lib/schemas";
import type { ShelfData } from "@/lib/shelf-data";
import { mind, type Placed } from "@/lib/shelves";
import { cn } from "@/lib/utils";
import { leadOf, unlessTitle } from "./worth-doing";

/* ───────── Search: always one step away ───────── */

export function HomeSearch() {
  const nav = useNavigate();
  const [q, setQ] = useState("");
  return (
    <form
      role="search"
      onSubmit={(e) => (e.preventDefault(), nav(q.trim() ? `/search?q=${encodeURIComponent(q.trim())}` : "/search?focus=1"))}
      className="relative w-full lg:max-w-md"
    >
      <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-mut" aria-hidden />
      <Input
        aria-label="Search or ask your notes"
        placeholder="Search, or ask your notes a question"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        className="h-10 rounded-lg pl-9 text-[14px]"
      />
    </form>
  );
}

/* ───────── Recently remembered ───────── */

const FEED_STEP = 8;
type Resource = { e: Entry; p: Placed };

/** What Pith preserved, newest first and grouped by day. Two lenses: whole notes, or the resources extracted from them. */
export function Remembered({
  items,
  data,
  hasMore,
  className,
}: {
  items: LibraryItem[];
  data: ShelfData;
  hasMore: boolean;
  className?: string;
}) {
  const [lens, setLens] = useState<"notes" | "resources">("notes");
  const [limit, setLimit] = useState(FEED_STEP);
  const fresh = items.filter((i) => isNew(i.created_at)).length;
  const entries = useEntries({});

  const resources = useMemo<Resource[]>(
    () =>
      (entries.data?.entries ?? [])
        .flatMap((e) => {
          const p = data.byId.get(e.note.id);
          return p ? [{ e, p }] : [];
        })
        .sort((a, b) => b.p.item.created_at.localeCompare(a.p.item.created_at)),
    [entries.data, data.byId],
  );

  const groups = useMemo(() => {
    const out: { label: string; notes: LibraryItem[]; res: Resource[] }[] = [];
    const rows: (LibraryItem | Resource)[] = lens === "notes" ? items : resources;
    for (const r of rows.slice(0, limit)) {
      const isNote = "created_at" in r;
      const label = dayLabel(isNote ? r.created_at : r.p.item.created_at);
      let g = out[out.length - 1];
      if (g?.label !== label) out.push((g = { label, notes: [], res: [] }));
      if (isNote) g.notes.push(r);
      else g.res.push(r);
    }
    return out;
  }, [lens, items, resources, limit]);
  const total = lens === "notes" ? items.length : resources.length;

  const tab = (id: "notes" | "resources", name: string, n: number) => (
    <button
      type="button"
      role="tab"
      aria-selected={lens === id}
      onClick={() => (setLens(id), setLimit(FEED_STEP))}
      className={cn(
        "h-7 rounded-md px-2 text-[13px] font-medium",
        lens === id ? "bg-ink text-paper" : "text-soft hover:bg-panel hover:text-ink",
      )}
    >
      {name} <span className={cn("tabular-nums", lens === id ? "opacity-70" : "text-mut")}>{n}</span>
    </button>
  );

  return (
    <section aria-label="Recently saved" className={className}>
      <SectionTitle
        actions={
          <Link to="/library" className="inline-flex h-8 items-center text-[13px] text-acc hover:underline">
            See all
          </Link>
        }
      >
        Recently saved{fresh > 0 && <span className="font-normal tracking-normal text-acc normal-case">{fresh} new</span>}
      </SectionTitle>
      {resources.length > 0 && (
        <div role="tablist" aria-label="Lens" className="mb-1 flex gap-1 border-b border-hair pb-2">
          {tab("notes", "Notes", items.length)}
          {tab("resources", "Resources", resources.length)}
        </div>
      )}

      {total === 0 ? (
        <p className="py-4 text-[13.5px] text-mut">
          {lens === "notes"
            ? "No finished notes yet. They appear as soon as they are read."
            : "No resources extracted yet. Films, repositories and tools Pith finds inside a note are listed here."}
        </p>
      ) : (
        <div>
          {groups.map((g) => (
            <div key={g.label}>
              <h3 className="pt-3 pb-1 text-[12px] font-medium text-mut">{g.label}</h3>
              <ul className="divide-y divide-hair border-y border-hair">
                {g.notes.map((i) => (
                  <NoteLine key={i.id} i={i} data={data} />
                ))}
                {g.res.map((r) => (
                  <ResourceLine key={r.e.id} r={r} data={data} />
                ))}
              </ul>
            </div>
          ))}
          <div className="flex items-center justify-between pt-2 text-[13px]">
            {total > limit ? (
              <button type="button" className="text-acc hover:underline" onClick={() => setLimit((l) => l + FEED_STEP)}>
                Show {Math.min(FEED_STEP, total - limit)} more
              </button>
            ) : (
              <span />
            )}
            {lens === "notes" && (hasMore || total <= limit) && (
              <Link to="/library" className="text-acc hover:underline">
                All knowledge
              </Link>
            )}
          </div>
        </div>
      )}
    </section>
  );
}

function ShelfTag({ id, data }: { id: string; data: ShelfData }) {
  if (id === "reference") return null;
  return (
    <span className="inline-flex items-center gap-1 text-[12.5px] text-mut">
      <ShelfIcon id={id} className="size-3.5" />
      {data.shelves.find((s) => s.id === id)?.name ?? id}
    </span>
  );
}

function NoteLine({ i, data }: { i: LibraryItem; data: ShelfData }) {
  const p = data.byId.get(i.id);
  const shelf = p?.placement.shelf ?? i.shelf;
  const title = cleanTitle(i.title, i.lead ?? i.host);
  const lead = unlessTitle(p ? leadOf(p) : (i.lead ?? ""), title);
  return (
    <li data-testid="note-row" className="group relative flex items-start gap-2.5 py-2.5">
      <div className="min-w-0 flex-1">
        <Link
          to={`/note/${i.id}`}
          data-row-link
          className="block truncate font-medium after:absolute after:inset-0 after:content-[''] group-hover:text-acc"
        >
          {isNew(i.created_at) && <span className="mr-2 inline-block size-2 rounded-full bg-acc align-middle" aria-label="New" />}
          {title}
        </Link>
        {lead && <p className="line-clamp-1 text-[13px] text-soft">{lead}</p>}
        <p className="mt-0.5 flex flex-wrap items-center gap-x-2.5 text-[12.5px] text-mut">
          <ShelfTag id={shelf} data={data} />
          {i.host && <span className="max-w-40 truncate">{i.host}</span>}
          {i.topics.slice(0, 2).map((t) => (
            <span key={t}>#{t}</span>
          ))}
        </p>
      </div>
      <span className="pt-0.5 text-[12.5px] text-mut tabular-nums">{when(i.created_at)}</span>
    </li>
  );
}

function ResourceLine({ r, data }: { r: Resource; data: ShelfData }) {
  const { e, p } = r;
  return (
    <li className="py-2.5">
      <p className={cn("line-clamp-2 text-[14px]", e.done_at && "text-mut line-through")}>{e.text}</p>
      <p className="mt-0.5 flex flex-wrap items-center gap-x-2.5 text-[12.5px] text-mut">
        <ShelfTag id={p.placement.shelf} data={data} />
        <span>
          from{" "}
          <Link to={`/note/${p.item.id}`} className="text-soft hover:text-acc">
            {cleanTitle(p.item.title, p.item.lead ?? p.item.host)}
          </Link>
        </span>
      </p>
    </li>
  );
}

/* ───────── Rediscovery: only with a stated reason ───────── */

const REASON: Record<string, string> = {
  intent: "You said why",
  topic: "Connects to this week",
  shelf: "Still waiting",
};

export function Rediscover({ data, resurfaced, className }: { data: ShelfData; resurfaced: Resurfaced | undefined; className?: string }) {
  const rows = (resurfaced?.items ?? []).flatMap((r) => {
    const p = data.byId.get(r.id);
    return p ? [{ p, r }] : [];
  });
  if (rows.length === 0) return null;
  return (
    <section aria-label="Worth revisiting" className={className}>
      <SectionTitle count={rows.length}>Worth revisiting</SectionTitle>
      <ul className="divide-y divide-hair border-y border-hair">
        {rows.map(({ p, r }) => (
          <li key={p.item.id} className="py-3">
            <p className="text-[11.5px] font-semibold tracking-[0.04em] text-acc uppercase">{REASON[String(r.kind)] ?? "Related"}</p>
            <Link to={`/note/${p.item.id}`} className="mt-0.5 block leading-snug font-medium hover:text-acc">
              {cleanTitle(p.item.title, p.item.lead ?? p.item.host)}
            </Link>
            <p className="mt-0.5 text-[13px] text-soft">{r.why}</p>
            <div className="mt-1 -ml-2 flex gap-0.5">
              <Button size="sm" variant="ghost" onClick={() => mind.snooze(p.item.id, 14)} title="Hide for two weeks">
                Not now
              </Button>
              <Button size="sm" variant="ghost" onClick={() => mind.hide(p.item.id)} title="Never suggest this note again">
                Stop suggesting
              </Button>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

/* ───────── Topics: what your notes are about (shelves are in the sidebar) ───────── */

export function Topics({ className }: { className?: string }) {
  const topics = useTopics();
  const top = [...(topics.data ?? [])].filter((t) => t.n > 1).sort((a, b) => b.n - a.n).slice(0, 14);
  if (top.length === 0) return null;
  return (
    <section aria-label="Topics" className={className}>
      <SectionTitle>Topics</SectionTitle>
      <ul className="flex flex-wrap gap-1.5">
        {top.map((t) => (
          <li key={t.name}>
            <Link
              to={`/library?topic=${encodeURIComponent(t.name)}`}
              className="inline-flex min-h-8 items-center gap-1 rounded-full border border-line px-2.5 text-[13px] text-soft hover:border-mut hover:text-ink"
            >
              {t.name} <span className="text-mut tabular-nums">{t.n}</span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

/* ───────── Jump back in ───────── */

export function JumpBackIn({ list, className }: { list: { id: string; title: string }[]; className?: string }) {
  if (list.length === 0) return null;
  return (
    <section aria-label="Jump back in" className={className}>
      <SectionTitle>Jump back in</SectionTitle>
      <ul className="divide-y divide-hair border-y border-hair">
        {list.map((c) => (
          <li key={c.id}>
            <Link to={`/note/${c.id}`} className="line-clamp-2 py-2 text-[14px] hover:text-acc">
              {c.title}
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

/* ───────── Capture + pick up ───────── */

export function CaptureBox({ lastCapture, className }: { lastCapture: string | null; className?: string }) {
  const { saveText, saveFiles } = useCapture();
  const form = useForm<{ text: string; why: string }>({ defaultValues: { text: "", why: "" } });
  const [busy, setBusy] = useState(false);
  const submit = form.handleSubmit(async (v) => {
    if (!v.text.trim()) return;
    setBusy(true);
    if (await saveText(v.text.trim(), v.why.trim() || undefined)) form.reset();
    setBusy(false);
  });
  return (
    <div className={cn("space-y-8", className)}>
      <section aria-label="Save">
        <SectionTitle>Save something</SectionTitle>
        <form onSubmit={submit} className="space-y-2">
          <Textarea rows={2} aria-label="Link or text to save" placeholder="Paste a link or text" {...form.register("text")} />
          <Input
            aria-label="Why are you saving it? (optional)"
            placeholder="Why? (optional, helps Pith place it)"
            {...form.register("why")}
          />
          <div className="flex items-center gap-2">
            <Button variant="primary" type="submit" loading={busy}>
              Save
            </Button>
            <label className="inline-flex h-9 cursor-pointer items-center gap-1.5 rounded-md border border-line bg-raise px-3 text-[13.5px] font-medium text-ink hover:bg-panel focus-within:outline-2 focus-within:outline-acc">
              <Paperclip className="size-3.5" aria-hidden /> Attach
              <input
                type="file"
                multiple
                className="sr-only"
                onChange={(e) => (saveFiles([...(e.target.files ?? [])]), (e.target.value = ""))}
              />
            </label>
          </div>
        </form>
        <p className="mt-2 text-[12.5px] text-mut">
          {lastCapture ? <>Last item arrived {when(lastCapture)}. </> : "Nothing has arrived yet. "}
          <Link to="/settings" className="inline-flex min-h-8 items-center text-acc underline underline-offset-2">
            Capture sources
          </Link>
        </p>
      </section>

    </div>
  );
}
