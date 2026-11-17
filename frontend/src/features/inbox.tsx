import { useWindowVirtualizer } from "@tanstack/react-virtual";
import { AlertCircle, CheckCircle2, ChevronRight, Clock, Loader2, RotateCcw } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router";
import { useCapture } from "@/app/capture";
import { AttentionCard } from "@/components/attention";
import { useToast } from "@/components/toast";
import { Button, Checkbox, Chip, EmptyState, ErrorState, PageHeader, Skeleton } from "@/components/ui";
import { cleanTitle, explainError, fullDate, plural, when } from "@/lib/format";
import { isNew } from "@/lib/local";
import { useAppState, useInbox, useInboxDetail, useRetry } from "@/lib/queries";
import type { InboxRow, InboxStatus } from "@/lib/schemas";
import { cn } from "@/lib/utils";
import { useSearchParams } from "react-router";

const GROUPS = {
  all: { label: "All", match: (_s: InboxStatus) => true },
  attention: { label: "Needs you", match: (s: InboxStatus) => s === "failed" || s === "needs_clarification" },
  working: { label: "In progress", match: (s: InboxStatus) => s === "new" || s === "pending" || s === "processing" },
  done: { label: "Done", match: (s: InboxStatus) => s === "processed" },
} as const;
type Group = keyof typeof GROUPS;

export function statusView(s: InboxStatus) {
  switch (s) {
    case "processed":
      return { label: "In library", tone: "ok" as const, Icon: CheckCircle2 };
    case "failed":
      return { label: "Failed", tone: "bad" as const, Icon: AlertCircle };
    case "needs_clarification":
      return { label: "Needs you", tone: "warn" as const, Icon: AlertCircle };
    case "processing":
      return { label: "Reading", tone: "accent" as const, Icon: Loader2 };
    default:
      return { label: "Waiting", tone: "neutral" as const, Icon: Clock };
  }
}

export function Inbox() {
  const [params, setParams] = useSearchParams();
  const group = (params.get("show") as Group) in GROUPS ? (params.get("show") as Group) : "all";
  const state = useAppState();
  const working = (state.data?.counts.pending ?? 0) + (state.data?.counts.processing ?? 0) + (state.data?.counts.new ?? 0) > 0;
  const inbox = useInbox(working);
  const { open } = useCapture();
  const toast = useToast();
  const retry = useRetry();
  const [sel, setSel] = useState<Set<string>>(new Set());
  const [openId, setOpenId] = useState<string | null>(null);

  useEffect(() => {
    document.title = "Inbox · Pith";
  }, []);

  const rows = useMemo(() => (inbox.data ?? []).slice().sort((a, b) => b.submitted_at.localeCompare(a.submitted_at)), [inbox.data]);
  const counts = useMemo(() => {
    const c: Record<Group, number> = { all: rows.length, attention: 0, working: 0, done: 0 };
    for (const r of rows) for (const g of ["attention", "working", "done"] as const) if (GROUPS[g].match(r.status)) c[g]++;
    return c;
  }, [rows]);
  const shown = useMemo(() => rows.filter((r) => GROUPS[group].match(r.status)), [rows, group]);
  const fresh = rows.filter((r) => isNew(r.submitted_at)).length;
  const selectable = (r: InboxRow) => r.status === "failed" || r.status === "needs_clarification";

  const retrySelected = async () => {
    const ids = [...sel];
    const res = await Promise.allSettled(ids.map((id) => retry.mutateAsync(id)));
    const bad = res.filter((r) => r.status === "rejected").length;
    setSel(new Set());
    toast(bad ? `${ids.length - bad} queued again; ${bad} could not be.` : `${plural(ids.length, "item")} queued again.`, { bad: !!bad });
  };

  return (
    <div className="enter mx-auto max-w-4xl">
      <PageHeader
        title="Inbox"
        sub={
          inbox.isSuccess
            ? `${plural(rows.length, "item")} captured${fresh ? ` · ${fresh} since you were last here` : ""}. Finished items live in the Library.`
            : "Everything that arrives, as it is read"
        }
        actions={<Button onClick={open}>Save something</Button>}
      />

      <div role="tablist" aria-label="Filter inbox" className="mb-3 flex gap-1 overflow-x-auto border-b border-hair">
        {(Object.keys(GROUPS) as Group[]).map((g) => (
          <button
            key={g}
            role="tab"
            aria-selected={group === g}
            onClick={() => (setParams(g === "all" ? {} : { show: g }, { replace: true }), setSel(new Set()))}
            className={cn(
              "-mb-px flex h-9 items-center gap-1.5 border-b-2 px-3 text-[13.5px] font-medium whitespace-nowrap",
              group === g ? "border-acc text-ink" : "border-transparent text-mut hover:text-ink",
            )}
          >
            {GROUPS[g].label}
            <span
              className={cn(
                "rounded-full px-1.5 text-[12px] tabular-nums",
                g === "attention" && counts.attention > 0 ? "bg-bad-tint text-bad" : "bg-panel text-mut",
              )}
            >
              {counts[g]}
            </span>
          </button>
        ))}
      </div>

      {group === "attention" && shown.length > 1 && (
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <Checkbox
            checked={sel.size > 0 && sel.size === shown.filter(selectable).length ? true : sel.size > 0 ? "indeterminate" : false}
            onCheckedChange={(c) => setSel(c === true ? new Set(shown.filter(selectable).map((r) => r.id)) : new Set())}
            aria-label="Select all items that need you"
          />
          <span className="text-[13.5px] text-soft">{sel.size > 0 ? `${sel.size} selected` : "Select all"}</span>
          <Button size="sm" disabled={sel.size === 0} loading={retry.isPending} onClick={() => void retrySelected()}>
            <RotateCcw className="size-3.5" aria-hidden /> Try again
          </Button>
        </div>
      )}

      {inbox.isPending ? (
        <div aria-busy className="space-y-2">
          {[0, 1, 2, 3, 4].map((i) => (
            <Skeleton key={i} className="h-16" />
          ))}
        </div>
      ) : inbox.isError ? (
        <ErrorState error={inbox.error} retry={() => void inbox.refetch()} />
      ) : shown.length === 0 ? (
        <EmptyState
          title={
            group === "attention"
              ? "Nothing needs you"
              : group === "working"
                ? "Nothing is being read"
                : group === "done"
                  ? "Nothing finished yet"
                  : "The inbox is empty"
          }
          action={
            group === "all" ? (
              <Button variant="primary" onClick={open}>
                Save something
              </Button>
            ) : undefined
          }
        >
          {group === "all"
            ? "Anything you save, from the drop folder, the share endpoint, the CLI or this page, shows up here while it is read."
            : "All clear."}
        </EmptyState>
      ) : (
        <Feed
          rows={shown}
          sel={sel}
          onSel={(id, on) => setSel((s) => (on ? new Set(s).add(id) : (s.delete(id), new Set(s))))}
          openId={openId}
          setOpenId={setOpenId}
          selectable={group === "attention"}
        />
      )}
      {rows.length >= 200 && (
        <p className="py-4 text-center text-[13px] text-mut">Showing the latest 200. Older finished items are in the Library.</p>
      )}
    </div>
  );
}

function Feed({
  rows,
  sel,
  onSel,
  openId,
  setOpenId,
  selectable,
}: {
  rows: InboxRow[];
  sel: Set<string>;
  onSel: (id: string, on: boolean) => void;
  openId: string | null;
  setOpenId: (id: string | null) => void;
  selectable: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const virt = useWindowVirtualizer({
    count: rows.length,
    estimateSize: () => 76,
    overscan: 8,
    scrollMargin: ref.current?.offsetTop ?? 0,
    getItemKey: (i) => rows[i]?.id ?? i,
  });
  return (
    <div ref={ref} className="overflow-hidden rounded-xl border border-line bg-raise" role="list" aria-label="Inbox items">
      <div style={{ height: virt.getTotalSize(), position: "relative" }}>
        {virt.getVirtualItems().map((v) => {
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
              <InboxItem
                row={r}
                open={openId === r.id}
                onToggle={() => setOpenId(openId === r.id ? null : r.id)}
                checked={sel.has(r.id)}
                onCheck={selectable ? (on) => onSel(r.id, on) : undefined}
              />
            </div>
          );
        })}
      </div>
    </div>
  );
}

function InboxItem({
  row,
  open,
  onToggle,
  checked,
  onCheck,
}: {
  row: InboxRow;
  open: boolean;
  onToggle: () => void;
  checked: boolean;
  onCheck?: (on: boolean) => void;
}) {
  const v = statusView(row.status);
  const fresh = isNew(row.submitted_at);
  const needs = row.status === "failed" || row.status === "needs_clarification";
  return (
    <div className={cn("border-b border-hair", checked && "bg-acc-tint/40")}>
      <div className="flex items-start gap-3 px-3 py-3 sm:px-4">
        {onCheck && needs && (
          <Checkbox className="mt-1" checked={checked} onCheckedChange={(c) => onCheck(c === true)} aria-label={`Select ${row.what}`} />
        )}
        <button type="button" onClick={onToggle} aria-expanded={open} className="flex min-w-0 flex-1 items-start gap-3 text-left">
          <ChevronRight className={cn("mt-1 size-4 shrink-0 text-mut transition-transform", open && "rotate-90")} aria-hidden />
          <span className="min-w-0 flex-1">
            <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
              {fresh && <span className="size-2 rounded-full bg-acc" aria-label="New since your last visit" />}
              <Chip tone={v.tone}>
                <v.Icon className={cn("size-3", row.status === "processing" && "animate-spin")} aria-hidden /> {v.label}
              </Chip>
              <span className="text-[12.5px] text-mut tabular-nums" title={fullDate(row.submitted_at)}>
                {when(row.submitted_at)}
              </span>
              {row.content_type && <span className="text-[12.5px] text-mut">{row.content_type}</span>}
            </span>
            <span className="mt-1 block truncate font-medium">{cleanTitle(row.what)}</span>
            {needs ? (
              <span className="mt-0.5 block truncate text-[13.5px] text-soft">{explainError(row.status, row.error).title}</span>
            ) : row.preview ? (
              <span className="mt-0.5 line-clamp-2 text-[13.5px] text-soft">{row.preview}</span>
            ) : row.user_context ? (
              <span className="mt-0.5 block truncate text-[13.5px] text-mut">Why: {row.user_context}</span>
            ) : null}
          </span>
        </button>
      </div>
      {open && <Detail row={row} />}
    </div>
  );
}

function Detail({ row }: { row: InboxRow }) {
  const d = useInboxDetail(row.id);
  const note = d.data?.items.find((i) => i.kind === "note") ?? d.data?.items.find((i) => i.kind === "summary") ?? d.data?.items[0];
  return (
    <div className="space-y-3 px-4 pb-4 pl-10 sm:pl-12">
      {(row.status === "failed" || row.status === "needs_clarification") && <AttentionCard row={row} />}
      {row.status === "processed" && (
        <p>
          {d.isPending ? (
            <Skeleton className="h-8 w-40" />
          ) : note ? (
            <Link
              to={`/note/${note.id}`}
              className="inline-flex h-9 items-center rounded-md bg-acc px-3.5 text-[13.5px] font-medium text-acc-ink hover:brightness-110"
            >
              Open note
            </Link>
          ) : (
            <span className="text-mut">The note was deleted.</span>
          )}
        </p>
      )}
      {row.user_context && (
        <p className="text-[13.5px]">
          <span className="font-medium text-soft">Why you saved it:</span> {row.user_context}
        </p>
      )}
      <div>
        <h3 className="mb-1 text-[12px] font-semibold tracking-[0.06em] text-mut uppercase">What happened</h3>
        {d.isPending ? (
          <Skeleton className="h-12" />
        ) : d.isError ? (
          <p className="text-[13px] text-bad">Could not load the history.</p>
        ) : d.data.events.length === 0 ? (
          <p className="text-[13px] text-mut">Waiting to be picked up.</p>
        ) : (
          <ol className="space-y-1 border-l border-line pl-3 text-[13px]">
            {d.data.events.map((e, i) => (
              <li key={i} className="text-soft">
                <span className="text-mut tabular-nums">{when(e.at)}</span> ·{" "}
                <span className="font-medium">{e.stage.replaceAll("_", " ")}</span>{" "}
                {e.detail ? <span className="text-mut">· {e.detail}</span> : null}
              </li>
            ))}
          </ol>
        )}
      </div>
    </div>
  );
}
