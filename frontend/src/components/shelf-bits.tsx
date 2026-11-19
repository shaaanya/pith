import {
  Check,
  Circle,
  CircleCheck,
  Clapperboard,
  Compass,
  FileText,
  Gamepad2,
  Headphones,
  Inbox,
  Library,
  ExternalLink,
  FolderInput,
  MapPin,
  Wrench,
} from "lucide-react";
import { Link } from "react-router";
import { cleanTitle, when } from "@/lib/format";
import { isNew } from "@/lib/local";
import { useShelfData } from "@/lib/shelf-data";
import { mind, type Placed } from "@/lib/shelves";
import { cn, safeHref } from "@/lib/utils";
import { Menu, MenuContent, MenuItem, MenuTrigger } from "./overlay";
import { Button } from "./ui";

const ICONS: Record<string, typeof Library> = {
  watch: Clapperboard,
  listen: Headphones,
  read: FileText,
  play: Gamepad2,
  try: Wrench,
  visit: MapPin,
  reference: Library,
  other: Inbox,
};
export function ShelfIcon({ id, className }: { id: string; className?: string }) {
  const I = ICONS[id] ?? Compass;
  return <I className={cn("size-[17px] shrink-0", className)} aria-hidden />;
}

/** One-click correction: move a note to another shelf. Placement is automatic, this is the override. */
export function MoveMenu({ placed, label = "Move", size = "sm" }: { placed: Placed; label?: string; size?: "sm" | "iconSm" }) {
  const { shelves } = useShelfData();
  const cur = placed.placement.shelf;
  return (
    <Menu>
      <MenuTrigger asChild>
        <Button size={size} variant="ghost" className="relative z-10" aria-label={size === "iconSm" ? "Move to another shelf" : undefined} title="Move to another shelf">
          {size === "sm" ? (
            <>
              <ShelfIcon id={cur} className="size-3.5" /> {label}
            </>
          ) : (
            <FolderInput className="size-4" aria-hidden />
          )}
        </Button>
      </MenuTrigger>
      <MenuContent>
        <p className="px-2.5 pt-1 pb-1.5 text-[11.5px] text-mut">Put on shelf</p>
        {shelves.map((s) => (
          <MenuItem key={s.id} onSelect={() => mind.move(placed.item.id, s.id)}>
            <ShelfIcon id={s.id} className="size-4 text-mut" />
            {s.name}
            {cur === s.id && <Check className="ml-auto size-3.5 text-acc" aria-label="Current shelf" />}
          </MenuItem>
        ))}
        {placed.placement.by === "you" && <MenuItem onSelect={() => mind.move(placed.item.id, undefined)}>Let Pith decide again</MenuItem>}
      </MenuContent>
    </Menu>
  );
}

/** Done toggle with a per-shelf verb ("Watched", "Tried"). */
export function DoneToggle({ placed, doneLabel, compact }: { placed: Placed; doneLabel?: string; compact?: boolean }) {
  const done = !!placed.state.done;
  const verb = doneLabel ?? "Done";
  const Icon = done ? CircleCheck : Circle;
  return (
    <button
      type="button"
      aria-pressed={done}
      aria-label={done ? `${verb}. Mark as to do again` : `Mark as ${verb.toLowerCase()}`}
      onClick={() => mind.setDone(placed.item.id, !done)}
      className={cn(
        "relative z-10 inline-flex items-center gap-1.5 rounded-md text-[13px] font-medium transition-colors",
        compact ? "size-8 justify-center pointer-coarse:size-11" : "h-7 px-2",
        done ? "text-ok hover:bg-ok-tint" : "text-mut hover:bg-panel hover:text-ink",
      )}
    >
      <Icon className="size-[18px]" aria-hidden />
      {!compact && <span>{done ? verb : `Mark ${verb.toLowerCase()}`}</span>}
    </button>
  );
}

/** Compact list row used on shelves and Home: what it is, why it sits here, and one-click correction. */
export function ShelfRow({
  placed,
  doneLabel,
  todo,
  showShelf,
  entries,
  openable,
}: {
  placed: Placed;
  doneLabel?: string;
  todo: boolean;
  showShelf?: boolean;
  entries?: { id: string; text: string }[];
  /** Offer a link to the original page (Try, Read: places you go next). */
  openable?: boolean;
}) {
  const { item, placement, state } = placed;
  const href = openable ? safeHref(item.url) : undefined;
  const title = cleanTitle(item.title, item.lead ?? item.host);
  const done = !!state.done;
  const stem = (item.title ?? "").replace(/[….]+$/, "").trim();
  const lead =
    item.lead && stem.length > 12 && item.lead.startsWith(stem) ? item.lead.slice(stem.length).replace(/^[\s….,:;-]+/, "") : item.lead;
  return (
    <li
      data-testid="shelf-row"
      className="group relative flex items-start gap-2.5 border-b border-hair px-3 py-3 last:border-b-0 hover:bg-panel/60 sm:px-4"
    >
      {todo && (
        <div className="-mt-0.5 -ml-1">
          <DoneToggle placed={placed} doneLabel={doneLabel} compact />
        </div>
      )}
      <div className="min-w-0 flex-1">
        <h3 className="flex items-center gap-2 leading-snug">
          {isNew(item.created_at) && <span className="size-2 shrink-0 rounded-full bg-acc" aria-label="New since your last visit" />}
          <Link
            to={`/note/${item.id}`}
            data-row-link
            className={cn(
              "truncate font-medium after:absolute after:inset-0 after:content-['']",
              done ? "text-mut line-through decoration-mut/50" : "text-ink",
            )}
          >
            {title}
          </Link>
        </h3>
        {lead && !done && !entries?.length && <p className="mt-0.5 line-clamp-2 text-[13.5px] leading-relaxed text-soft">{lead}</p>}
        {item.intent && (
          <p className="mt-1 line-clamp-1 text-[13px] text-soft">
            <span className="text-mut">Why saved ·</span> {item.intent}
          </p>
        )}
        {!done && entries && entries.length > 0 && (
          <ul className="relative z-10 mt-1.5 space-y-px" aria-label="Items in this note">
            {entries.slice(0, 5).map((e) => (
              <li key={e.id}>
                <button
                  type="button"
                  onClick={() => mind.entry(e.id, true)}
                  aria-label={`Mark done: ${e.text}`}
                  className="flex w-full items-start gap-2 rounded px-1 py-0.5 text-left text-[13.5px] hover:bg-panel"
                >
                  <Circle className="mt-0.5 size-4 shrink-0 text-mut" aria-hidden />
                  <span className="line-clamp-2">{e.text}</span>
                </button>
              </li>
            ))}
            {entries.length > 5 && <li className="ml-7 text-[12.5px] text-mut">{entries.length - 5} more in the note</li>}
          </ul>
        )}
        <p className="mt-1.5 flex flex-wrap items-center gap-x-2.5 gap-y-0.5 text-[12.5px] text-mut">
          {showShelf && (
            <span className="inline-flex items-center gap-1 text-soft">
              <ShelfIcon id={placement.shelf} className="size-3.5" />
              <span className="capitalize">{placement.shelf.replace(/^u-/, "").replace(/-/g, " ")}</span>
            </span>
          )}
          {item.host && <span>{item.host}</span>}
          {!todo && item.topics.slice(0, 3).map((t) => <span key={t}>#{t}</span>)}
          <span className="tabular-nums">{when(item.created_at)}</span>
          {done && state.done && <span className="text-ok">done {when(state.done)}</span>}
          {(placement.by === "model" || placement.by === "you") && (
            <span className="text-mut/90" title="Why it is on this shelf">
              {placement.why}
            </span>
          )}
        </p>
      </div>
      {href && (
        <a
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          aria-label={`Open the original of ${title}`}
          title="Open the original"
          className="relative z-10 grid size-8 shrink-0 place-items-center rounded-md text-mut hover:bg-panel hover:text-ink"
        >
          <ExternalLink className="size-4" aria-hidden />
        </a>
      )}
      <MoveMenu placed={placed} size="iconSm" />
    </li>
  );
}
