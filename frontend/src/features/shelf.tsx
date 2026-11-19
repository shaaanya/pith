import { Check, Circle, CircleCheck, Dices, Eye, EyeOff, Plus, Search, Trash2, Undo2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, Navigate, useParams, useSearchParams } from "react-router";
import { Confirm } from "@/components/overlay";
import { MoveMenu, ShelfIcon, ShelfRow } from "@/components/shelf-bits";
import { Button, EmptyState, Input, PageHeader, Skeleton } from "@/components/ui";
import { cleanTitle, plural, when } from "@/lib/format";
import { isNew } from "@/lib/local";
import { useEntries } from "@/lib/queries";
import { useShelfData } from "@/lib/shelf-data";
import { BUILTIN, layout, mind, shelfById, usePrefs, type Placed } from "@/lib/shelves";
import { cn } from "@/lib/utils";
import { leadOf, unlessTitle } from "./home/worth-doing";

const PAGE = 40;
/** Shelves where each extracted title is the thing you choose between (a film, an album, a game, a place). */
const QUEUE = new Set(["watch", "listen", "play", "visit"]);
const PICK: Record<string, string> = { watch: "Pick something to watch", listen: "Pick something to listen to", play: "Pick something to play", visit: "Pick a place" };

type Candidate = { key: string; name: string; detail: string; note: Placed; entry?: { id: string; text: string } };

/** "Prisoners (2013): a thriller" -> name and detail. Falls back to the whole text as the name. */
function splitEntry(text: string): { name: string; detail: string } {
  const m = /^(.{3,70}?)(?::\s+|\s+[-–—]\s+)(.+)$/.exec(text);
  return m ? { name: m[1]!, detail: m[2]! } : { name: text, detail: "" };
}

export function ShelfPage() {
  const { id = "" } = useParams();
  const data = useShelfData();
  const [params, setParams] = useSearchParams();
  const [q, setQ] = useState("");
  const [limit, setLimit] = useState(PAGE);
  const [confirm, setConfirm] = useState(false);
  const shelf = shelfById(data.shelves, id);
  const topic = params.get("topic") ?? "";
  const oldest = params.get("sort") === "oldest";
  const show = params.get("show") === "done" ? "done" : "todo";
  const openEntries = useEntries({ shelf: id, done: "0" });
  const doneEntries = useEntries({ shelf: id, done: "1" });

  useEffect(() => {
    document.title = `${shelf?.name ?? "Shelf"} · Pith`;
  }, [shelf?.name]);
  useEffect(() => setLimit(PAGE), [id, show, q, topic]);

  const entryMap = useMemo(() => {
    const m = new Map<string, { id: string; text: string }[]>();
    for (const e of openEntries.data?.entries ?? []) m.set(e.note.id, [...(m.get(e.note.id) ?? []), e]);
    return m;
  }, [openEntries.data]);
  const all = useMemo(() => data.byShelf.get(id) ?? [], [data.byShelf, id]);
  const rows = useMemo(() => {
    const term = q.trim().toLowerCase();
    const out = all.filter((p) => {
      if (topic && !p.item.topics.includes(topic)) return false;
      if (shelf?.todo && show === "todo" && p.state.done) return false;
      if (shelf?.todo && show === "done" && !p.state.done) return false;
      if (!term) return true;
      return `${p.item.title} ${p.item.lead ?? ""} ${p.item.intent ?? ""} ${p.item.host ?? ""} ${p.item.topics.join(" ")}`.toLowerCase().includes(term);
    });
    return oldest ? [...out].reverse() : out;
  }, [all, q, show, shelf?.todo, topic, oldest]);
  const topics = useMemo(() => {
    const c = new Map<string, number>();
    for (const p of all) for (const t of p.item.topics) c.set(t, (c.get(t) ?? 0) + 1);
    return [...c].sort((a, b) => b[1] - a[1]).slice(0, 24);
  }, [all]);
  const setParam = (k: string, v: string) =>
    setParams((o) => { const n = new URLSearchParams(o); if (v) n.set(k, v); else n.delete(k); return n; }, { replace: true });

  if (!shelf) return <Navigate to="/shelves" replace />;
  const doneN = all.filter((p) => p.state.done).length + (doneEntries.data?.entries.length ?? 0);
  const openN = all.filter((p) => !p.state.done).length;
  const isOther = shelf.id === "other";
  const queue = shelf.todo && (QUEUE.has(shelf.id) || !shelf.builtin);
  const reference = !shelf.todo && !isOther;
  const seg = (v: "todo" | "done", label: string, n: number) => (
    <button
      key={v}
      type="button"
      aria-pressed={show === v}
      onClick={() => setParam("show", v === "todo" ? "" : v)}
      className={cn("h-9 rounded px-3 text-[13px] font-medium", show === v ? "bg-raise text-ink shadow-[0_0_0_1px_var(--line)]" : "text-mut hover:text-ink")}
    >
      {label} <span className="text-mut tabular-nums">{n}</span>
    </button>
  );

  const body = !data.ready ? (
    <div aria-busy className="space-y-2">
      <Skeleton className="h-16" />
      <Skeleton className="h-16" />
      <Skeleton className="h-16" />
    </div>
  ) : queue ? (
    <Queue shelf={shelf} notes={all} openEntries={openEntries.data?.entries ?? []} doneEntries={doneEntries.data?.entries ?? []} show={show} q={q} topic={topic} />
  ) : rows.length === 0 ? (
    <Empty shelfName={shelf.name} custom={!shelf.builtin} filtered={!!q || !!topic} done={show === "done"} anyDone={doneN > 0} />
  ) : (
    <>
      <ul className="overflow-hidden rounded-xl border border-line bg-raise" aria-label={`${shelf.name} notes`}>
        {rows.slice(0, limit).map((p) =>
          reference ? (
            <RefRow key={p.item.id} placed={p} />
          ) : (
            <ShelfRow key={p.item.id} placed={p} todo={shelf.todo} doneLabel={shelf.doneLabel} entries={shelf.todo ? entryMap.get(p.item.id) : undefined} openable={shelf.todo} />
          ),
        )}
      </ul>
      {rows.length > limit && (
        <div className="py-4 text-center">
          <Button onClick={() => setLimit((l) => l + PAGE)}>
            Show {Math.min(PAGE, rows.length - limit)} more · {rows.length - limit} left
          </Button>
        </div>
      )}
    </>
  );

  const tools = (
    <div className="mb-4 flex flex-wrap items-center gap-3">
      {shelf.todo && (
        <div role="group" aria-label="Show" className="flex rounded-md border border-line p-0.5">
          {seg("todo", shelf.todo && queue ? "Up next" : "To do", openN)}
          {seg("done", shelf.doneLabel ?? "Done", doneN)}
        </div>
      )}
      {(reference ? all.length > 5 : all.length > 8) && (
        <div className="relative min-w-48 flex-1 sm:max-w-80">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-mut" aria-hidden />
          <Input aria-label={`Filter ${shelf.name}`} placeholder={reference ? "Find in Reference" : `Filter ${shelf.name}`} value={q} onChange={(e) => setQ(e.target.value)} className="h-9 pl-8" />
        </div>
      )}
      {!queue && all.length > 3 && (
        <button type="button" onClick={() => setParam("sort", oldest ? "" : "oldest")} className="h-9 rounded-md px-2.5 text-[13px] text-soft hover:bg-panel hover:text-ink">
          {oldest ? "Oldest first" : "Newest first"}
        </button>
      )}
    </div>
  );

  return (
    <div className="enter @container">
      <PageHeader
        title={
          <span className="flex items-center gap-3">
            <ShelfIcon id={shelf.id} className="size-6 text-acc" />
            {shelf.name}
          </span>
        }
        sub={
          reference
            ? `${plural(all.length, "note")} to keep and look up. Nothing here is a to-do.`
            : shelf.blurb
        }
        actions={
          !shelf.builtin && (
            <Button size="sm" variant="ghost" onClick={() => setConfirm(true)}>
              <Trash2 className="size-3.5" aria-hidden /> Delete shelf
            </Button>
          )
        }
      />

      {isOther && (
        <p className="mb-4 max-w-[62ch] rounded-lg border border-line bg-panel/60 px-4 py-3 text-[13.5px] text-soft">
          Pith could not find a shelf for these (no saved reason, no known site, nothing readable yet). Nothing is hidden here. Use the
          shelf button on a row to give it a home.
        </p>
      )}

      {reference && data.ready ? (
        <div className="grid gap-x-10 @4xl:grid-cols-[13rem_minmax(0,1fr)]">
          {topics.length > 1 && (
            <nav aria-label="Topics in Reference" className="@max-4xl:order-first @4xl:sticky @4xl:top-6 @4xl:self-start">
              <h2 className="mb-1.5 text-[12px] font-semibold tracking-[0.06em] text-mut uppercase">Topics</h2>
              <ul className="flex flex-wrap gap-1.5 @4xl:max-h-[70dvh] @4xl:flex-col @4xl:flex-nowrap @4xl:gap-0 @4xl:overflow-y-auto">
                {topics.map(([t, n]) => (
                  <li key={t}>
                    <button
                      type="button"
                      aria-pressed={topic === t}
                      onClick={() => setParam("topic", topic === t ? "" : t)}
                      className={cn(
                        "inline-flex min-h-8 w-full items-center justify-between gap-2 rounded-full border px-2.5 text-[13px] @4xl:rounded-md @4xl:border-0 @4xl:px-2",
                        topic === t ? "border-ink bg-ink text-paper @4xl:bg-panel @4xl:font-medium @4xl:text-ink" : "border-line text-soft hover:text-ink @4xl:hover:bg-panel",
                      )}
                    >
                      <span className="truncate">{t}</span> <span className="tabular-nums opacity-70">{n}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </nav>
          )}
          <div className="min-w-0 @max-4xl:mt-4">
            {tools}
            {body}
          </div>
        </div>
      ) : (
        <>
          {tools}
          {body}
        </>
      )}
      {data.truncated && <p className="mt-4 text-[13px] text-mut">Showing shelves for your newest 3,000 notes. Older notes stay in All knowledge and search.</p>}

      <Confirm
        open={confirm}
        onOpenChange={setConfirm}
        title={`Delete the ${shelf.name} shelf?`}
        body="Its notes are not deleted: they go back to automatic placement."
        confirmLabel="Delete shelf"
        onConfirm={() => (mind.removeShelf(shelf.id), setConfirm(false))}
      />
    </div>
  );
}

/** Reference row: built for finding and reading, so no done mark, no placement chatter. */
function RefRow({ placed }: { placed: Placed }) {
  const { item } = placed;
  const title = cleanTitle(item.title, item.lead ?? item.host);
  const lead = unlessTitle(leadOf(placed), title);
  return (
    <li data-testid="shelf-row" className="group relative flex items-start gap-2 border-b border-hair px-3 py-3 last:border-b-0 hover:bg-panel/60 sm:px-4">
      <div className="min-w-0 flex-1">
        <h3 className="flex items-center gap-2 leading-snug">
          {isNew(item.created_at) && <span className="size-2 shrink-0 rounded-full bg-acc" aria-label="New since your last visit" />}
          <Link to={`/note/${item.id}`} data-row-link className="truncate font-medium after:absolute after:inset-0 after:content-['']">
            {title}
          </Link>
        </h3>
        {lead && <p className="mt-0.5 line-clamp-2 text-[13.5px] leading-relaxed text-soft">{lead}</p>}
        {item.intent && (
          <p className="mt-1 line-clamp-1 text-[13px] text-soft">
            <span className="text-mut">Why saved ·</span> {item.intent}
          </p>
        )}
        <p className="mt-1 flex flex-wrap items-center gap-x-2.5 text-[12.5px] text-mut">
          {item.host && <span>{item.host}</span>}
          {item.topics.slice(0, 3).map((t) => (
            <span key={t}>#{t}</span>
          ))}
          <span className="tabular-nums">{when(item.created_at)}</span>
          {placed.placement.by === "you" && <span>{placed.placement.why}</span>}
        </p>
      </div>
      <MoveMenu placed={placed} size="iconSm" />
    </li>
  );
}

/**
 * Watch / Listen / Play / Visit: the individual titles Pith found are the things you choose between, so each is its own card
 * (a note that has no extracted titles stands in as one card). "Pick one" answers "what tonight?" without scrolling.
 */
function Queue({
  shelf,
  notes,
  openEntries,
  doneEntries,
  show,
  q,
  topic,
}: {
  shelf: { id: string; name: string; doneLabel?: string };
  notes: Placed[];
  openEntries: { id: string; text: string; note: { id: string } }[];
  doneEntries: { id: string; text: string; note: { id: string; title: string } }[];
  show: "todo" | "done";
  q: string;
  topic: string;
}) {
  const [pick, setPick] = useState<string | null>(null);
  const verb = (shelf.doneLabel ?? "Done").toLowerCase();
  const term = q.trim().toLowerCase();
  const byNote = useMemo(() => {
    const m = new Map<string, { id: string; text: string }[]>();
    for (const e of openEntries) m.set(e.note.id, [...(m.get(e.note.id) ?? []), e]);
    return m;
  }, [openEntries]);

  const { cands, wholeNotes } = useMemo(() => {
    const out: Candidate[] = [];
    let whole = 0;
    for (const p of notes) {
      if (p.state.done || (topic && !p.item.topics.includes(topic))) continue;
      const es = byNote.get(p.item.id);
      if (es?.length) for (const e of es) out.push({ key: e.id, ...splitEntry(e.text), note: p, entry: e });
      else {
        whole++;
        const title = cleanTitle(p.item.title, p.item.lead ?? p.item.host);
        out.push({ key: p.item.id, name: title, detail: p.item.intent ?? unlessTitle(leadOf(p), title), note: p });
      }
    }
    const f = term ? out.filter((c) => `${c.name} ${c.detail} ${c.note.item.title}`.toLowerCase().includes(term)) : out;
    return { cands: f, wholeNotes: whole };
  }, [notes, byNote, topic, term]);

  const picked = cands.find((c) => c.key === pick);
  const tick = (c: Candidate) => (c.entry ? mind.entry(c.entry.id, true) : mind.setDone(c.note.item.id, true));

  if (show === "done") {
    const doneNotes = notes.filter((p) => p.state.done);
    if (doneEntries.length === 0 && doneNotes.length === 0)
      return <EmptyState title={`Nothing ${verb} yet`}>Tick the circle on anything here when you have got to it. It moves to this list and is never deleted.</EmptyState>;
    return (
      <ul className="overflow-hidden rounded-xl border border-line bg-raise" aria-label={`${shelf.doneLabel ?? "Done"}`}>
        {doneEntries.map((e) => (
          <li key={e.id} className="flex items-center gap-3 border-b border-hair px-4 py-2.5 last:border-b-0">
            <CircleCheck className="size-[18px] shrink-0 text-ok" aria-hidden />
            <span className="min-w-0 flex-1 text-mut line-through decoration-mut/50">{e.text}</span>
            <Button size="sm" variant="ghost" onClick={() => mind.entry(e.id, false)} aria-label={`Put back: ${e.text}`}>
              <Undo2 className="size-3.5" aria-hidden /> Put back
            </Button>
          </li>
        ))}
        {doneNotes.map((p) => (
          <ShelfRow key={p.item.id} placed={p} todo doneLabel={shelf.doneLabel} />
        ))}
      </ul>
    );
  }

  if (cands.length === 0)
    return term || topic ? (
      <EmptyState title={`Nothing on ${shelf.name} matches`}>Try a different word.</EmptyState>
    ) : (
      <EmptyState title="All caught up">Nothing is waiting on this shelf. What you have {verb} is under {shelf.doneLabel ?? "Done"}.</EmptyState>
    );

  return (
    <div>
      {cands.length > 2 && (
        <div className="mb-4">
          {picked ? (
            <div className="rounded-xl border border-acc/40 bg-acc-tint/40 p-4" aria-live="polite">
              <p className="text-[12px] font-semibold tracking-[0.06em] text-acc uppercase">Your pick</p>
              <p className="mt-1 font-serif text-[22px] leading-snug font-semibold">{picked.name}</p>
              {picked.detail && <p className="mt-1 text-[14px] text-soft">{picked.detail}</p>}
              <p className="mt-1 text-[12.5px] text-mut">
                From <Link to={`/note/${picked.note.item.id}`} className="underline underline-offset-2 hover:text-ink">{cleanTitle(picked.note.item.title, picked.note.item.lead ?? picked.note.item.host)}</Link>
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                <Button variant="primary" onClick={() => (tick(picked), setPick(null))}>
                  <Check className="size-4" aria-hidden /> I {verb} it
                </Button>
                <Button onClick={() => setPick(cands[Math.floor(Math.random() * cands.length)]!.key)}>
                  <Dices className="size-4" aria-hidden /> Another
                </Button>
                <Button variant="ghost" onClick={() => setPick(null)}>
                  Close
                </Button>
              </div>
            </div>
          ) : (
            <Button onClick={() => setPick(cands[Math.floor(Math.random() * cands.length)]!.key)}>
              <Dices className="size-4" aria-hidden /> {PICK[shelf.id] ?? "Pick one for me"}
            </Button>
          )}
        </div>
      )}
      <ul className="grid gap-3 @2xl:grid-cols-2 @6xl:grid-cols-3" aria-label={`Up next on ${shelf.name}`}>
        {cands.map((c) => (
          <li key={c.key} data-testid="shelf-row" className={cn("group relative flex gap-2.5 rounded-xl border bg-raise p-3.5", picked?.key === c.key ? "border-acc" : "border-line")}>
            <button
              type="button"
              onClick={() => tick(c)}
              aria-label={`Mark ${verb}: ${c.name}`}
              className="-mt-0.5 -ml-1 grid size-8 shrink-0 place-items-center rounded-md text-mut hover:bg-panel hover:text-ok"
            >
              <Circle className="size-[18px]" aria-hidden />
            </button>
            <div className="min-w-0 flex-1">
              <p className="leading-snug font-medium">{c.name}</p>
              {c.detail && <p className="mt-0.5 line-clamp-3 text-[13.5px] text-soft">{c.detail}</p>}
              <p className="mt-1.5 flex flex-wrap items-center gap-x-2 text-[12.5px] text-mut">
                {c.entry ? (
                  <Link to={`/note/${c.note.item.id}`} className="max-w-full truncate hover:text-ink">
                    from {cleanTitle(c.note.item.title, c.note.item.lead ?? c.note.item.host)}
                  </Link>
                ) : (
                  <Link to={`/note/${c.note.item.id}`} className="hover:text-ink">
                    Open note
                  </Link>
                )}
                {c.note.item.host && <span>{c.note.item.host}</span>}
                <span className="tabular-nums">{when(c.note.item.created_at)}</span>
              </p>
            </div>
            {!c.entry && <MoveMenu placed={c.note} size="iconSm" />}
          </li>
        ))}
      </ul>
      {wholeNotes > 0 && cands.some((c) => c.entry) && (
        <p className="mt-4 text-[12.5px] text-mut">Where Pith could not pick out separate titles, the whole saved note is listed instead.</p>
      )}
    </div>
  );
}

function Empty({ shelfName, custom, filtered, done, anyDone }: { shelfName: string; custom: boolean; filtered: boolean; done: boolean; anyDone: boolean }) {
  if (filtered) return <EmptyState title="Nothing on this shelf matches">Try a different word.</EmptyState>;
  if (done) return <EmptyState title="Nothing marked done yet">Tick the circle on a row when you have got to it. It leaves the to-do list but is never deleted.</EmptyState>;
  if (anyDone) return <EmptyState title="Everything here is done">Switch to the done list to look back at it.</EmptyState>;
  return (
    <EmptyState title={`${shelfName} is empty`}>
      {custom
        ? "Put notes here with the shelf button on any row or in the reader. Pith does not file into your own shelves automatically yet."
        : "Pith puts a note here when your saved reason or the site it came from says so. You can also move any note here yourself."}
    </EmptyState>
  );
}

export function Shelves() {
  const m = usePrefs();
  const data = useShelfData();
  const [name, setName] = useState("");
  const [blurb, setBlurb] = useState("");
  useEffect(() => {
    document.title = "Shelves · Pith";
  }, []);
  const add = () => {
    if (!name.trim()) return;
    mind.addShelf(name, blurb);
    setName("");
    setBlurb("");
  };
  const hiddenBuiltins = BUILTIN.filter((s) => m.hidden.includes(s.id) && s.id !== "other");

  return (
    <div className="enter">
      <PageHeader
        title="Shelves"
        sub="What each note is useful for. Pith places notes by your saved reason or the site they came from. Topics, which say what a note is about, cut across all of these."
        actions={
          <Link to="/library" className="text-[13.5px] text-acc hover:underline">
            All knowledge
          </Link>
        }
      />
      <ul className="grid gap-px overflow-hidden rounded-xl border border-line bg-line sm:grid-cols-2" aria-label="Shelves">
        {[...data.shelves].sort((a, b) => Number((data.byShelf.get(b.id)?.length ?? 0) > 0) - Number((data.byShelf.get(a.id)?.length ?? 0) > 0)).map((s) => {
          const list = data.byShelf.get(s.id) ?? [];
          const open = list.filter((p) => !p.state.done).length;
          return (
            <li key={s.id} className="group relative flex items-start gap-3 bg-raise px-4 py-3.5 hover:bg-panel/70">
              <ShelfIcon id={s.id} className="mt-0.5 size-5 text-acc" />
              <div className="min-w-0 flex-1">
                <Link to={`/shelf/${s.id}`} className="font-medium after:absolute after:inset-0 after:content-['']">
                  {s.name}
                </Link>
                <p className="text-[13px] text-mut">{s.blurb}</p>
              </div>
              <span className="text-right text-[12.5px] text-mut tabular-nums">
                {data.ready ? (
                  <>
                    {list.length === 0 ? (
                      "empty"
                    ) : (
                      <>
                        <span className="block text-[15px] font-medium text-ink">{s.todo ? open : list.length}</span>
                        {s.todo ? "to do" : "notes"}
                      </>
                    )}
                  </>
                ) : (
                  "…"
                )}
              </span>
              {s.builtin && s.id !== "other" && (
                <button
                  type="button"
                  onClick={() => layout.toggleHidden(s.id)}
                  aria-label={`Hide the ${s.name} shelf`}
                  title="Hide this shelf"
                  className="relative z-10 -mr-1 self-center rounded p-1 text-mut hover:text-ink focus-visible:opacity-100 md:opacity-0 md:group-hover:opacity-100"
                >
                  <EyeOff className="size-4" aria-hidden />
                </button>
              )}
            </li>
          );
        })}
      </ul>

      {hiddenBuiltins.length > 0 && (
        <p className="mt-3 flex flex-wrap items-center gap-2 text-[13px] text-mut">
          Hidden:
          {hiddenBuiltins.map((s) => (
            <button
              key={s.id}
              type="button"
              onClick={() => layout.toggleHidden(s.id)}
              className="inline-flex items-center gap-1 rounded-full border border-line px-2.5 py-0.5 hover:text-ink"
            >
              <Eye className="size-3.5" aria-hidden /> Show {s.name}
            </button>
          ))}
        </p>
      )}

      <section className="mt-10 grid gap-8 lg:grid-cols-2" aria-label="Make a shelf">
        <form onSubmit={(e) => (e.preventDefault(), add())} className="space-y-2">
          <h2 className="text-[12px] font-semibold tracking-[0.07em] text-mut uppercase">Make your own shelf</h2>
          <Input aria-label="Shelf name" placeholder="Name, for example Recipes to cook" value={name} onChange={(e) => setName(e.target.value)} maxLength={40} />
          <Input aria-label="What belongs here" placeholder="What belongs here (one line)" value={blurb} onChange={(e) => setBlurb(e.target.value)} maxLength={120} />
          <Button type="submit" variant="primary" disabled={!name.trim()}>
            <Plus className="size-4" aria-hidden /> Add shelf
          </Button>
        </form>
        <div className="space-y-2 text-[13.5px] text-soft">
          <h2 className="text-[12px] font-semibold tracking-[0.07em] text-mut uppercase">How placement works</h2>
          <p>
            When a note is saved, the model reads it, your reason for saving it and the site it came from, and picks the best shelf from
            this list. If no model is running, simple rules decide: your reason, then a known site (GitHub goes to Try, Letterboxd to
            Watch). A video is not put on Watch just because it is a video: the note already holds what it said. Where you move a note,
            it stays.
          </p>
          <p className="text-mut">
            Write a one-line description for your own shelves: it is what the model reads to decide what belongs there. Shelves, your moves
            and done marks are saved with your notes (they are in <code className="font-mono text-[12px]">pith backup</code>). Run{" "}
            <code className="font-mono text-[12px]">pith place</code> to place notes saved before.
          </p>
        </div>
      </section>
    </div>
  );
}
