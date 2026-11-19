import { Circle, CircleCheck, ExternalLink } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router";
import { DoneToggle, MoveMenu, ShelfIcon } from "@/components/shelf-bits";
import { SectionTitle } from "@/components/ui";
import { cleanTitle, when } from "@/lib/format";
import { useEntries } from "@/lib/queries";
import type { Entry } from "@/lib/schemas";
import type { ShelfData } from "@/lib/shelf-data";
import { mind, type Placed } from "@/lib/shelves";
import { cn, safeHref } from "@/lib/utils";

/** The part of the lead that is not just the (truncated) title repeated. */
export function leadOf(p: Placed): string {
  const { title, lead } = p.item;
  const stem = (title ?? "").replace(/[….]+$/, "").trim();
  if (lead && stem.length > 12 && lead.trim().replace(/[….]+$/, "") === stem) return "";
  if (lead && stem.length > 12 && lead.startsWith(stem)) return lead.slice(stem.length).replace(/^[\s….,:;-]+/, "");
  return lead ?? "";
}

/** Drop a preview that only repeats the title being shown. */
export const unlessTitle = (lead: string, title: string) => {
  const n = (x: string) =>
    x
      .trim()
      .replace(/[….]+$/, "")
      .toLowerCase();
  return n(lead) === n(title) || n(title).startsWith(n(lead)) ? "" : lead;
};

const FRESH_DAYS = 21;
const weeksAgo = (iso: string) => {
  const w = Math.round((Date.now() - Date.parse(iso)) / (7 * 86_400_000));
  return w <= 1 ? "a week" : `${w} weeks`;
};
const ENTRY_PREVIEW = 3;
const PER_SHELF = 3;

/** Notes saved with a stated reason come first (that is what you meant to act on), then newest. */
function rank(a: Placed, b: Placed) {
  const ia = a.item.intent ? 1 : 0;
  const ib = b.item.intent ? 1 : 0;
  return ib - ia || b.item.created_at.localeCompare(a.item.created_at);
}

const VERB: Record<string, string> = {
  watch: "to watch",
  listen: "to listen to",
  read: "to read",
  play: "to play",
  try: "to try",
  visit: "to visit",
};

/**
 * Up next: what you saved with an intention, grouped by what you meant to do with it. Each group says how much is waiting
 * ("2 to try") and links to its shelf: this is shelf information, not a copy of the sidebar. Shelves with nothing waiting do not appear.
 */
/** Open to-do notes by shelf, most relevant first. Shared so Home can avoid repeating what Up next already shows. */
export function groupOpen(data: ShelfData) {
  return data.shelves
    .filter((s) => s.todo)
    .map((s) => ({ s, rows: data.open.filter((p) => p.placement.shelf === s.id).sort(rank) }))
    .filter((g) => g.rows.length > 0)
    .sort((a, b) => rank(a.rows[0]!, b.rows[0]!));
}
export const upNextShown = (data: ShelfData) => new Set(groupOpen(data).flatMap((g) => g.rows.slice(0, PER_SHELF).map((p) => p.item.id)));

export function UpNext({ data, className }: { data: ShelfData; className?: string }) {
  const entries = useEntries({ done: "0" });
  const byNote = useMemo(() => {
    const m = new Map<string, Entry[]>();
    for (const e of entries.data?.entries ?? []) m.set(e.note.id, [...(m.get(e.note.id) ?? []), e]);
    return m;
  }, [entries.data]);

  const groups = useMemo(() => groupOpen(data), [data]);
  if (groups.length === 0) return null;
  const stale = (p: Placed) => Date.now() - Date.parse(p.item.created_at) > FRESH_DAYS * 86_400_000;

  return (
    <section aria-label="Up next" className={className}>
      <SectionTitle count={data.open.length}>Up next</SectionTitle>
      <div className="space-y-6">
        {groups.map(({ s, rows }) => (
          <div key={s.id}>
            <div className="flex items-center gap-2 border-b border-hair pb-1.5">
              <ShelfIcon id={s.id} className="text-acc" />
              <h3 className="text-[14px] font-semibold">
                {s.name}{" "}
                <span className="font-normal text-mut">
                  {rows.length} {VERB[s.id] ?? "to do"}
                </span>
              </h3>
              <Link to={`/shelf/${s.id}`} className="ml-auto inline-flex h-8 items-center text-[13px] text-acc hover:underline">
                {rows.length > PER_SHELF ? `All ${rows.length}` : "Open"}
                <span className="sr-only"> on the {s.name} shelf</span>
              </Link>
            </div>
            <ul>
              {rows.slice(0, PER_SHELF).map((p) => (
                <TodoRow key={p.item.id} p={p} doneLabel={s.doneLabel} entries={byNote.get(p.item.id) ?? []} showShelf={false} stale={stale(p)} />
              ))}
            </ul>
          </div>
        ))}
      </div>
    </section>
  );
}

function TodoRow({
  p,
  doneLabel,
  entries,
  showShelf,
  stale,
}: {
  p: Placed;
  doneLabel?: string;
  entries: Entry[];
  showShelf: boolean;
  stale: boolean;
}) {
  const [all, setAll] = useState(false);
  const { item, placement } = p;
  const title = cleanTitle(item.title, item.lead ?? item.host);
  const lead = unlessTitle(leadOf(p), title);
  const href = safeHref(item.url);
  const list = all ? entries : entries.slice(0, ENTRY_PREVIEW);
  return (
    <li data-testid="shelf-row" className="border-b border-hair py-3 last:border-b-0">
      <div className="flex items-start gap-1.5">
        <div className="-mt-0.5 -ml-1.5">
          <DoneToggle placed={p} doneLabel={doneLabel} compact />
        </div>
        <div className="min-w-0 flex-1">
          <h3 className="leading-snug">
            <Link to={`/note/${item.id}`} className="font-medium text-ink hover:text-acc">
              {title}
            </Link>
          </h3>
          {item.intent ? (
            <p className="mt-0.5 line-clamp-2 text-[13.5px] text-soft">
              <span className="text-mut">You saved it to:</span> {item.intent}
            </p>
          ) : (
            lead && <p className="mt-0.5 line-clamp-2 text-[13.5px] text-soft">{lead}</p>
          )}
          {entries.length > 0 && (
            <ul className="mt-1.5 space-y-px" aria-label={`Items in ${title}`}>
              {list.map((e) => (
                <li key={e.id}>
                  <button
                    type="button"
                    onClick={() => mind.entry(e.id, true)}
                    aria-label={`Mark done: ${e.text}`}
                    className="group/e flex w-full items-start gap-2 rounded px-1 py-0.5 text-left text-[13.5px] text-ink hover:bg-panel"
                  >
                    <Circle className="mt-0.5 size-4 shrink-0 text-mut group-hover/e:hidden" aria-hidden />
                    <CircleCheck className="mt-0.5 hidden size-4 shrink-0 text-ok group-hover/e:block" aria-hidden />
                    <span className="line-clamp-2 min-w-0 flex-1">{e.text}</span>
                  </button>
                </li>
              ))}
              {entries.length > ENTRY_PREVIEW && (
                <li>
                  <button type="button" onClick={() => setAll((v) => !v)} className="ml-7 text-[12.5px] text-acc hover:underline">
                    {all ? "Show fewer" : `${entries.length - ENTRY_PREVIEW} more in this note`}
                  </button>
                </li>
              )}
            </ul>
          )}
          <p className="mt-1 flex flex-wrap items-center gap-x-2.5 gap-y-0.5 text-[12.5px] text-mut">
            {showShelf && (
              <span className="inline-flex items-center gap-1 text-soft">
                <ShelfIcon id={placement.shelf} className="size-3.5" />
                <span className="capitalize">{placement.shelf.replace(/^u-/, "").replace(/-/g, " ")}</span>
              </span>
            )}
            {item.host && <span>{item.host}</span>}
            <span className={cn("tabular-nums", stale && "text-warn")}>
              {stale ? `Waiting ${weeksAgo(item.created_at)}` : when(item.created_at)}
            </span>
            {href && (
              <a href={href} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 hover:text-ink">
                <ExternalLink className="size-3" aria-hidden /> Source
              </a>
            )}
          </p>
        </div>
        <MoveMenu placed={p} size="iconSm" />
      </div>
    </li>
  );
}
