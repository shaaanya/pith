import { AlertTriangle, ArrowLeft, Copy, ExternalLink, Pencil, RotateCcw, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useForm } from "react-hook-form";
import { Link, useNavigate, useParams } from "react-router";
import { z } from "zod";
import { zodResolver } from "@hookform/resolvers/zod";
import { Confirm } from "@/components/overlay";
import { useToast } from "@/components/toast";
import { DoneToggle, MoveMenu, ShelfIcon } from "@/components/shelf-bits";
import { Button, Checkbox, Chip, EmptyState, ErrorState, Input, Label, Skeleton, Textarea } from "@/components/ui";
import { ApiError, blobUrl } from "@/lib/api";
import { cleanTitle, fullDate, hostOf, when } from "@/lib/format";
import { useHotkeys } from "@/lib/hotkeys";
import { asMarkdown, Markdown } from "@/lib/markdown";
import { useShelfData } from "@/lib/shelf-data";
import { mind, shelfById, type Placed } from "@/lib/shelves";
import { useDeleteItem, useInboxDetail, useItem, useReprocess, useUpdateItem } from "@/lib/queries";
import type { Entry, ItemDetail, LibraryItem, NoteUnit } from "@/lib/schemas";
import { cn, safeHref } from "@/lib/utils";

/** Same rule the backend uses for cited excerpts: YouTube time, PDF page, else the plain URL. */
export function deepLink(platform: string | null | undefined, url: string | null | undefined, locator: string | null | undefined) {
  const base = safeHref(url);
  if (!base) return undefined;
  const t = /^t=(\d+(?:\.\d+)?)/.exec(locator ?? "");
  if (t && platform === "youtube") return `${base}${base.includes("?") ? "&" : "?"}t=${Math.floor(Number(t[1]))}s`;
  const p = /^page=(\d+)/.exec(locator ?? "");
  if (p) return `${base}#page=${p[1]}`;
  return base;
}

const niceLocator = (l: string) => {
  const t = /^t=(\d+(?:\.\d+)?)/.exec(l);
  if (t) {
    const s = Math.floor(Number(t[1]));
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  }
  const p = /^page=(\d+)/.exec(l);
  if (p) return `p. ${p[1]}`;
  return l.startsWith("char=") ? "passage" : l;
};

const Edit = z.object({
  title: z.string().trim().min(1, "A note needs a title.").max(500, "Keep the title under 500 characters."),
  body: z.string().trim().min(1, "A note needs some content."),
});

export function Reader() {
  const { id = "" } = useParams();
  const q = useItem(id);
  const nav = useNavigate();
  const toast = useToast();
  const [editing, setEditing] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const del = useDeleteItem();
  const re = useReprocess();

  useEffect(() => {
    if (id) mind.opened(id);
  }, [id]);
  const back = () => (history.length > 1 ? nav(-1) : nav("/library"));
  const d = q.data;
  const copy = async () => {
    if (!d) return;
    try {
      await navigator.clipboard.writeText(asMarkdown(cleanTitle(d.title), d.body));
      toast("Copied as Markdown.");
    } catch {
      toast("Copying is blocked by the browser.", { bad: true });
    }
  };
  useHotkeys(
    {
      e: () => d && setEditing(true),
      c: () => void copy(),
      Escape: () => (editing ? setEditing(false) : document.querySelector('[role="dialog"]') ? undefined : back()),
    },
    !!d,
  );
  useEffect(() => {
    document.title = d ? `${cleanTitle(d.title)} · Pith` : "Pith";
  }, [d]);

  if (q.isPending) return <ReaderSkeleton />;
  if (q.isError) {
    const gone = q.error instanceof ApiError && q.error.status === 404;
    return gone ? (
      <EmptyState title="This note is gone" action={<Button onClick={() => nav("/library")}>Back to the library</Button>}>
        It was deleted, or the link is wrong.
      </EmptyState>
    ) : (
      <ErrorState error={q.error} retry={() => void q.refetch()} />
    );
  }
  const item = q.data;

  return (
    <article className="enter">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <Button variant="ghost" size="sm" onClick={back} className="-ml-2">
          <ArrowLeft className="size-4" aria-hidden /> Back
        </Button>
        {!editing && (
          <div className="flex flex-wrap gap-1.5" role="toolbar" aria-label="Note actions">
            <Button size="sm" onClick={() => void copy()}>
              <Copy className="size-3.5" aria-hidden /> Copy
            </Button>
            <Button size="sm" onClick={() => setEditing(true)}>
              <Pencil className="size-3.5" aria-hidden /> Edit
            </Button>
            <Button
              size="sm"
              loading={re.isPending}
              onClick={() =>
                re.mutate(item.id, {
                  onSuccess: () => toast("Reading it again. Your edits are kept."),
                  onError: (e) => toast(e instanceof ApiError ? e.message : "Could not queue that.", { bad: true }),
                })
              }
            >
              <RotateCcw className="size-3.5" aria-hidden /> Read again
            </Button>
            <Button size="sm" variant="danger" onClick={() => setConfirm(true)}>
              <Trash2 className="size-3.5" aria-hidden /> Delete
            </Button>
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 gap-x-12 gap-y-8 xl:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="min-w-0">{editing ? <Editor item={item} done={() => setEditing(false)} /> : <NoteBody item={item} />}</div>
        {!editing && <Rail item={item} />}
      </div>

      <Confirm
        open={confirm}
        onOpenChange={setConfirm}
        title="Delete this note?"
        body="It disappears from the library and search. The original file is kept."
        confirmLabel="Delete"
        busy={del.isPending}
        onConfirm={() =>
          del.mutate(item.id, {
            onSuccess: () => (toast("Note deleted."), nav("/library", { replace: true })),
            onError: () => toast("Could not delete.", { bad: true }),
          })
        }
      />
    </article>
  );
}

function ReaderSkeleton() {
  return (
    <div aria-busy className="max-w-[68ch] space-y-3">
      <Skeleton className="h-8 w-3/4" />
      <Skeleton className="h-4 w-1/3" />
      <Skeleton className="mt-6 h-20 w-full" />
      <Skeleton className="h-4 w-full" />
      <Skeleton className="h-4 w-11/12" />
      <Skeleton className="h-4 w-4/5" />
    </div>
  );
}

function Editor({ item, done }: { item: ItemDetail; done: () => void }) {
  const upd = useUpdateItem(item.id);
  const toast = useToast();
  const form = useForm<z.infer<typeof Edit>>({ resolver: zodResolver(Edit), defaultValues: { title: item.title, body: item.body } });
  const save = form.handleSubmit((v) =>
    upd.mutate(v, {
      onSuccess: () => (toast("Saved."), done()),
      onError: (e) => toast(e instanceof ApiError ? e.message : "Could not save.", { bad: true }),
    }),
  );
  return (
    // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions -- Cmd/Ctrl+Enter shortcut; focus is always in a field inside
    <form
      onSubmit={save}
      className="max-w-[68ch] space-y-3"
      onKeyDown={(e) => {
        if ((e.metaKey || e.ctrlKey) && e.key === "Enter") void save();
      }}
    >
      <div>
        <Label htmlFor="ed-title">Title</Label>
        <Input id="ed-title" className="h-10 text-[16px] font-semibold" {...form.register("title")} />
        {form.formState.errors.title && <p className="mt-1 text-[13px] text-bad">{form.formState.errors.title.message}</p>}
      </div>
      <div>
        <Label htmlFor="ed-body" hint="Markdown">
          Content
        </Label>
        <Textarea id="ed-body" rows={20} className="font-mono text-[13.5px]" {...form.register("body")} />
        {form.formState.errors.body && <p className="mt-1 text-[13px] text-bad">{form.formState.errors.body.message}</p>}
      </div>
      <p className="text-[13px] text-mut">
        Your edits are kept if Pith reads this note again. The structured view is replaced by your text.
      </p>
      <div className="flex gap-2">
        <Button variant="primary" type="submit" loading={upd.isPending}>
          Save changes
        </Button>
        <Button onClick={done}>Cancel</Button>
        <span className="ml-auto self-center text-[12.5px] text-mut">⌘↵ to save · Esc to cancel</span>
      </div>
    </form>
  );
}

const UNIT_ORDER = ["step", "fact", "claim", "warning", "resource"] as const;
const UNIT_TITLE: Record<string, string> = {
  step: "Steps",
  fact: "Facts",
  claim: "Claims",
  warning: "Watch out",
  resource: "Resources",
  other: "More",
};

function NoteBody({ item }: { item: ItemDetail }) {
  const noteIntent = item.note?.intent;
  const inboxId = noteIntent?.text ? null : (item.inbox[0]?.inbox_id ?? null);
  const saved = useInboxDetail(inboxId);
  const typedReason = saved.data?.user_context?.trim();
  const intent = noteIntent?.text ? noteIntent : typedReason ? { state: "explicit", text: typedReason } : null;
  const units = item.note?.units ?? [];
  const structured = units.length > 0 && !item.user_edited;
  const [mode, setMode] = useState<"structured" | "markdown">(structured ? "structured" : "markdown");
  const low = item.confidence != null && item.confidence < 0.5;
  const sourceUrl = item.source?.url;
  const meta = [
    item.source?.platform && item.source.platform !== "unknown" ? item.source.platform : null,
    hostOf(sourceUrl),
    item.source?.content_type,
  ].filter(Boolean);

  return (
    <div>
      <h1 className="font-serif text-[30px] leading-[1.2] font-semibold tracking-[-0.01em] text-balance">
        {cleanTitle(item.title, item.source?.title ?? hostOf(sourceUrl))}
      </h1>
      <p className="mt-2 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-[13px] text-mut">
        {meta.length > 0 && <span>{meta.join(" · ")}</span>}
        <span title={fullDate(item.created_at)}>Saved {when(item.created_at)}</span>
        {item.user_edited && <Chip tone="accent">Edited by you</Chip>}
        {item.provenance === "inferred" && <Chip tone="neutral">Written by Pith</Chip>}
        {low && <Chip tone="warn">Low confidence</Chip>}
        {item.flagged && <Chip tone="warn">Flagged</Chip>}
      </p>

      <ShelfBar detail={item} />

      {intent?.text && (
        <aside className="mt-5 max-w-[68ch] rounded-lg border border-acc/30 bg-acc-tint/60 px-4 py-3" aria-label="Why you saved this">
          <p className="text-[12px] font-semibold tracking-[0.06em] text-acc uppercase">
            {intent.state === "explicit" ? "Why you saved this" : "Why this was probably saved"}
          </p>
          <p className="mt-0.5 font-serif text-[16.5px]">{intent.text}</p>
          {intent.state && intent.state !== "explicit" && (
            <p className="mt-1 text-[12.5px] text-mut">Pith inferred this. You did not write a reason.</p>
          )}
        </aside>
      )}

      {units.length > 0 && !item.user_edited && (
        <div role="group" aria-label="Note view" className="mt-6 inline-flex rounded-md border border-line p-0.5">
          {(["structured", "markdown"] as const).map((m) => (
            <button
              key={m}
              type="button"
              aria-pressed={mode === m}
              onClick={() => setMode(m)}
              className={cn(
                "h-7 rounded px-2.5 text-[13px] font-medium",
                mode === m ? "bg-raise text-ink shadow-[0_0_0_1px_var(--line)]" : "text-mut hover:text-ink",
              )}
            >
              {m === "structured" ? "With sources" : "Markdown"}
            </button>
          ))}
        </div>
      )}

      <div className="mt-5">
        {mode === "structured" && structured ? (
          <Units units={units} platform={item.source?.platform} url={sourceUrl} entries={item.entries} />
        ) : (
          <Markdown source={item.body} />
        )}
        {mode === "markdown" && !item.body.trim() && <p className="text-mut">This note has no text.</p>}
      </div>
    </div>
  );
}

/** Units are plain text with `code` spans: render the spans as code instead of showing the backticks. */
function Inline({ text }: { text?: string | null }) {
  return (
    <>
      {(text ?? "").split(/(`[^`]+`)/g).map((t, i) =>
        t.startsWith("`") && t.endsWith("`") && t.length > 2 ? <code key={i}>{t.slice(1, -1)}</code> : <span key={i}>{t}</span>,
      )}
    </>
  );
}

const normText = (t: string | null | undefined) => (t ?? "").replace(/\s+/g, " ").trim().toLowerCase();

function Units({ units, platform, url, entries }: { units: NoteUnit[]; platform?: string | null; url?: string | null; entries: Entry[] }) {
  const entryOf = useMemo(() => new Map(entries.map((e) => [normText(e.text), e])), [entries]);
  const groups = useMemo(() => {
    const g = new Map<string, NoteUnit[]>();
    for (const u of units) {
      const k = (UNIT_ORDER as readonly string[]).includes(u.type ?? "") ? (u.type as string) : "other";
      g.set(k, [...(g.get(k) ?? []), u]);
    }
    // Keep the source order when everything is the same kind; otherwise group by kind.
    return [...g.entries()].sort(
      (a, b) => (UNIT_ORDER as readonly string[]).indexOf(a[0]) - (UNIT_ORDER as readonly string[]).indexOf(b[0]),
    );
  }, [units]);

  const loc = (u: NoteUnit) => {
    if (!u.locator) return null;
    const href = deepLink(platform, url, u.locator);
    const label = niceLocator(u.locator);
    return href ? (
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className="rounded border border-line px-1.5 py-px font-sans text-[11.5px] whitespace-nowrap text-mut hover:border-acc hover:text-acc"
        title="Open the source at this point"
      >
        {label}
      </a>
    ) : (
      <span className="rounded border border-hair px-1.5 py-px font-sans text-[11.5px] whitespace-nowrap text-mut">{label}</span>
    );
  };
  const weak = (u: NoteUnit) => (u.support != null && u.support < 0.7 ? <Chip tone="warn">partly supported</Chip> : null);

  return (
    <div className="prose-pith space-y-7">
      {groups.map(([kind, list]) => (
        <section key={kind} aria-label={UNIT_TITLE[kind]}>
          {groups.length > 1 && <h2 className={cn("!mt-0 mb-2", kind === "warning" && "text-bad")}>{UNIT_TITLE[kind]}</h2>}
          {kind === "resource" ? (
            <ul className="!list-none !pl-0">
              {list.length > 1 && (
                <li className="!mt-0 mb-2 font-sans text-[12.5px] text-mut">
                  {list.filter((u) => entryOf.get(normText(u.text))?.done_at).length} of {list.length} done · each one is tracked on its own
                </li>
              )}
              {list.map((u, i) => {
                const entry = entryOf.get(normText(u.text));
                const done = !!entry?.done_at;
                return (
                  <li key={i} className="flex items-start gap-3 !mt-1.5 rounded-md py-1">
                    <Checkbox
                      className="mt-[7px]"
                      checked={done}
                      disabled={!entry}
                      onCheckedChange={(c) => entry && mind.entry(entry.id, c === true)}
                      aria-label={`${done ? "Mark as to do" : "Mark as done"}: ${u.text}`}
                    />
                    <span className={cn(done && "text-mut line-through decoration-mut/50")}>
                      <Inline text={u.text} />{" "}
                      <span className="ml-1 inline-flex items-center gap-1.5 align-middle">
                        {loc(u)}
                        {weak(u)}
                      </span>
                    </span>
                  </li>
                );
              })}
            </ul>
          ) : kind === "step" ? (
            <ol>
              {list.map((u, i) => (
                <li key={i} className="pl-1">
                  <Inline text={u.text} />{" "}
                  <span className="ml-1 inline-flex items-center gap-1.5 align-middle">
                    {loc(u)}
                    {weak(u)}
                  </span>
                </li>
              ))}
            </ol>
          ) : kind === "warning" ? (
            <ul className="!list-none !pl-0 space-y-2">
              {list.map((u, i) => (
                <li key={i} className="flex gap-2.5 rounded-lg border border-bad/30 bg-bad-tint px-3 py-2 !font-serif">
                  <AlertTriangle className="mt-1.5 size-4 shrink-0 text-bad" aria-hidden />
                  <span>
                    <Inline text={u.text} />{" "}
                    <span className="ml-1 inline-flex items-center gap-1.5 align-middle">
                      {loc(u)}
                      {weak(u)}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <ul>
              {list.map((u, i) => (
                <li key={i}>
                  {u.focus && (
                    <span className="mr-1.5 rounded bg-acc-tint px-1 font-sans text-[11px] font-semibold text-acc uppercase">
                      your focus
                    </span>
                  )}
                  <Inline text={u.text} />{" "}
                  <span className="ml-1 inline-flex items-center gap-1.5 align-middle">
                    {loc(u)}
                    {weak(u)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      ))}
    </div>
  );
}

/** Where this note lives and its to-do state. Placement is automatic; this is where it is corrected. */
function ShelfBar({ detail }: { detail: ItemDetail }) {
  const data = useShelfData();
  // the note index is capped, so an older note comes from its own detail
  const p: Placed = data.byId.get(detail.id) ?? {
    item: { id: detail.id } as LibraryItem,
    placement: { shelf: detail.shelf, by: detail.placement.by, why: detail.placement.why },
    state: { done: detail.state.done_at ?? undefined, snooze: detail.state.snooze_until ?? undefined, hide: detail.state.hidden || undefined },
  };
  const shelf = shelfById(data.shelves, p.placement.shelf);
  return (
    <div
      className="mt-4 flex max-w-[68ch] flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-hair bg-panel/50 px-3 py-1.5 text-[13px]"
      role="group"
      aria-label="Shelf"
    >
      <span className="inline-flex items-center gap-1.5 font-medium">
        <ShelfIcon id={p.placement.shelf} className="size-4 text-acc" />
        {shelf?.name ?? "Other"} shelf
      </span>
      <span className="text-mut">{p.placement.why}</span>
      <span className="ml-auto flex items-center gap-1">
        {shelf?.todo && <DoneToggle placed={p} doneLabel={shelf.doneLabel} />}
        <MoveMenu placed={p} label="Move" />
      </span>
    </div>
  );
}

function Rail({ item }: { item: ItemDetail }) {
  const src = item.source;
  const href = safeHref(src?.url);
  const isImage = src?.content_type === "image";
  const first = item.inbox[0]?.inbox_id ?? null;
  const [openMentions, setOpenMentions] = useState(false);
  const mentionsInbox = useInboxDetail(openMentions ? first : null);
  const mentionsId = mentionsInbox.data?.items.find((i) => i.kind === "mentions")?.id ?? "";
  const mentions = useItem(mentionsId);
  const note = item.note;

  return (
    <aside className="space-y-6 text-[13.5px] xl:border-l xl:border-hair xl:pl-6" aria-label="About this note">
      <Block title="Source">
        <p className="font-medium break-words">{cleanTitle(src?.title ?? item.title)}</p>
        {href && (
          <a
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-1 inline-flex items-center gap-1 text-acc underline underline-offset-2"
          >
            Open original <ExternalLink className="size-3.5" aria-hidden />
          </a>
        )}
        {src?.blob_sha256 && (
          <div className="mt-2">
            {isImage && <img src={blobUrl(src.blob_sha256)} alt="" className="mb-2 max-h-48 rounded-md border border-hair" />}
            <a href={blobUrl(src.blob_sha256)} className="text-acc underline underline-offset-2" download>
              {isImage ? "Download image" : "Download saved file"}
            </a>
          </div>
        )}
        {item.inbox.length > 0 && (
          <p className="mt-2 text-mut">
            Saved {item.inbox.length > 1 ? `${item.inbox.length} times` : "once"}, first {when(item.inbox[0]?.added_at)}.
          </p>
        )}
      </Block>

      {item.topics.length > 0 && (
        <Block title="Topics">
          <div className="flex flex-wrap gap-1.5">
            {item.topics.map((t) => (
              <Link
                key={t}
                to={`/library?topic=${encodeURIComponent(t)}`}
                className="rounded-full border border-line px-2.5 py-0.5 text-[13px] text-soft hover:border-acc hover:text-acc"
              >
                {t}
              </Link>
            ))}
          </div>
        </Block>
      )}

      {item.entities.length > 0 && (
        <Block title="Names and tools">
          <div className="flex flex-wrap gap-1.5">
            {item.entities.map((t) => (
              <Link
                key={t}
                to={`/search?q=${encodeURIComponent(t)}`}
                className="rounded-md bg-panel px-2 py-0.5 text-[13px] text-soft hover:text-acc"
                title="Find everywhere this appears"
              >
                {t}
              </Link>
            ))}
          </div>
        </Block>
      )}

      {item.related.length > 0 && (
        <Block title="Related">
          <ul className="space-y-1.5">
            {item.related.map((r) => (
              <li key={r.id}>
                <Link to={`/note/${r.id}`} className="hover:text-acc">
                  {cleanTitle(r.title)}
                </Link>{" "}
                {r.type === "duplicate" && <Chip tone="warn">very similar</Chip>}
              </li>
            ))}
          </ul>
        </Block>
      )}

      {first && (
        <details onToggle={(e) => setOpenMentions((e.currentTarget as HTMLDetailsElement).open)}>
          <summary className="cursor-pointer text-[12px] font-semibold tracking-[0.06em] text-mut uppercase">Also mentioned</summary>
          <div className="mt-2 text-soft">
            {mentionsInbox.isPending || (mentionsId && mentions.isPending) ? (
              <Skeleton className="h-10" />
            ) : mentions.data ? (
              <Markdown source={mentions.data.body} className="prose-pith !text-[14px]" />
            ) : (
              <p className="text-mut">Nothing was mentioned only briefly.</p>
            )}
          </div>
        </details>
      )}

      {item.citations.length > 0 && (
        <details>
          <summary className="cursor-pointer text-[12px] font-semibold tracking-[0.06em] text-mut uppercase">
            Source passages · {item.citations.length}
          </summary>
          <ul className="mt-2 space-y-2.5">
            {item.citations.map((c) => (
              <li key={c.segment_id} className="rounded-md border border-hair bg-panel/60 p-2.5">
                {c.locator && <p className="mb-1 font-mono text-[11.5px] text-mut">{niceLocator(c.locator)}</p>}
                <p className="font-serif text-[14px] leading-relaxed">{c.text}</p>
              </li>
            ))}
          </ul>
        </details>
      )}

      <details>
        <summary className="cursor-pointer text-[12px] font-semibold tracking-[0.06em] text-mut uppercase">How this note was made</summary>
        <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-mut">
          <dt>Method</dt>
          <dd className="text-soft">
            {item.extracted_by === "verbatim" ? "Kept as written (short text)" : (item.extracted_by ?? "unknown")}
          </dd>
          <dt>Version</dt>
          <dd className="text-soft">
            {note?.version ?? "n/a"} · revision {item.version ?? 1}
          </dd>
          <dt>Updated</dt>
          <dd className="text-soft">{item.updated_at ? fullDate(item.updated_at) : "n/a"}</dd>
        </dl>
        {note && (note.limits.length > 0 || note.gaps.length > 0 || note.repairs.length > 0 || Object.keys(note.dropped).length > 0) && (
          <div className="mt-2 space-y-1.5 text-soft">
            {note.limits.map((l, i) => (
              <p key={`l${i}`}>Limit: {String(l)}</p>
            ))}
            {note.gaps.map((l, i) => (
              <p key={`g${i}`}>Gap: {String(l)}</p>
            ))}
            {note.repairs.length > 0 && <p>{note.repairs.length} term(s) corrected from the description.</p>}
            {Object.entries(note.dropped).map(([k, v]) => (
              <p key={k}>
                Left out {String(v)} unsupported {k}.
              </p>
            ))}
          </div>
        )}
      </details>
    </aside>
  );
}

const Block = ({ title, children }: { title: string; children: ReactNode }) => (
  <section>
    <h2 className="mb-1.5 text-[12px] font-semibold tracking-[0.06em] text-mut uppercase">{title}</h2>
    {children}
  </section>
);
