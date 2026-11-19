import { Flag } from "lucide-react";
import { Link } from "react-router";
import { cleanTitle, when } from "@/lib/format";
import { isNew } from "@/lib/local";
import type { LibraryItem } from "@/lib/schemas";
import { cn } from "@/lib/utils";
import { Checkbox, Chip } from "./ui";

const TYPE_LABEL: Record<string, string> = {
  note: "Note",
  url: "Link",
  web: "Article",
  article: "Article",
  pdf: "PDF",
  video: "Video",
  audio: "Audio",
  image: "Image",
};
const typeLabel = (t?: string | null) => (t ? (TYPE_LABEL[t] ?? t) : null);

export function NoteRow({
  item,
  selected,
  onSelect,
  selecting,
  active,
}: {
  item: LibraryItem;
  selected?: boolean;
  onSelect?: (id: string, on: boolean) => void;
  selecting?: boolean;
  active?: boolean;
}) {
  const fresh = isNew(item.created_at);
  const title = cleanTitle(item.title, item.lead ?? item.host);
  const t = typeLabel(item.type);
  // The backend title is the truncated first line of the same text: do not repeat it in the preview.
  const stem = (item.title ?? "").replace(/[….]+$/, "").trim();
  const lead =
    item.lead && stem.length > 12 && item.lead.startsWith(stem) ? item.lead.slice(stem.length).replace(/^[\s….,:;-]+/, "") : item.lead;
  return (
    <div
      data-testid="note-row"
      className={cn(
        "group relative flex gap-3 border-b border-hair px-3 py-3 transition-colors hover:bg-panel/70 sm:px-4",
        selected && "bg-acc-tint/50",
        active && "bg-panel",
      )}
    >
      {onSelect && (
        <div className={cn("pt-0.5 pointer-coarse:-m-2.5 pointer-coarse:p-2.5", !selecting && "md:absolute md:top-3.5 md:left-1 md:opacity-0 md:group-hover:opacity-100 md:group-focus-within:opacity-100")}>
          <Checkbox checked={!!selected} onCheckedChange={(c) => onSelect(item.id, c === true)} aria-label={`Select ${title}`} />
        </div>
      )}
      <div className="min-w-0 flex-1">
        <h3 className="flex items-center gap-2 leading-snug">
          {fresh && <span className="size-2 shrink-0 rounded-full bg-acc" title="New since your last visit" aria-label="New" />}
          <Link
            to={`/note/${item.id}`}
            className="truncate font-medium text-ink after:absolute after:inset-0 after:content-['']"
            data-row-link
          >
            {title}
          </Link>
          {item.flagged && <Flag className="size-3.5 shrink-0 text-warn" aria-label="Flagged" />}
        </h3>
        {lead && <p className="mt-0.5 line-clamp-2 text-[13.5px] leading-relaxed text-soft">{lead}</p>}
        {item.intent && (
          <p className="mt-1 line-clamp-1 text-[13px] text-mut">
            <span className="font-medium text-soft">Why saved:</span> {item.intent}
          </p>
        )}
        <p className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[12.5px] text-mut">
          {t && <Chip tone="neutral">{t}</Chip>}
          {item.host && <span>{item.host}</span>}
          {item.topics.slice(0, 3).map((x) => (
            <Chip key={x} tone="outline">
              {x}
            </Chip>
          ))}
          {item.topics.length > 3 && <span>+{item.topics.length - 3}</span>}
          <span className="ml-auto tabular-nums">{when(item.created_at)}</span>
        </p>
      </div>
    </div>
  );
}
