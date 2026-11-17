import { FolderOpen, Globe, Loader2, Cpu } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { Link } from "react-router";
import { useCapture } from "@/app/capture";
import { AttentionCard } from "@/components/attention";
import { NoteRow } from "@/components/note-row";
import { Button, Chip, EmptyState, ErrorState, Input, PageHeader, SectionTitle, Skeleton, Textarea } from "@/components/ui";
import { cleanTitle, fullDate, plural, when } from "@/lib/format";
import { isNew, lastVisit } from "@/lib/local";
import { useAppState, useDigest, useInbox, useLibrary } from "@/lib/queries";
import { statusView } from "./inbox";

const greeting = () => {
  const h = new Date().getHours();
  return h < 5 ? "Late night" : h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
};

export function Today() {
  const state = useAppState();
  const busy = (state.data?.counts.pending ?? 0) + (state.data?.counts.processing ?? 0) + (state.data?.counts.new ?? 0) > 0;
  const lib = useLibrary({}, busy);
  const first = lib.data?.pages[0];
  const digest = useDigest();
  const inbox = useInbox(false);

  useEffect(() => {
    document.title = "Today · Pith";
  }, []);

  const items = useMemo(() => lib.data?.pages.flatMap((p) => p.items) ?? [], [lib.data]);
  const fresh = items.filter((i) => isNew(i.created_at));
  const attention = first?.attention ?? [];
  const active = first?.active ?? [];
  const shown = (fresh.length ? fresh : items).slice(0, 8);
  const lastCapture = useMemo(
    () => (inbox.data ?? []).reduce<string | null>((m, r) => (!m || r.submitted_at > m ? r.submitted_at : m), null),
    [inbox.data],
  );

  if (lib.isPending) return <TodaySkeleton />;
  if (lib.isError) return <ErrorState error={lib.error} retry={() => void lib.refetch()} />;

  const totalNew = lastVisit ? (fresh.length >= items.length && lib.hasNextPage ? `${fresh.length}+` : String(fresh.length)) : null;
  const nothing = (first?.total ?? 0) === 0 && attention.length === 0 && active.length === 0;

  return (
    <div className="enter">
      <PageHeader
        title={greeting()}
        sub={
          lastVisit ? (
            <>
              Since you were last here ({fullDate(lastVisit)}):{" "}
              <strong className="font-medium text-ink">
                {totalNew === "0" ? "no new notes" : `${totalNew} new ${totalNew === "1" ? "note" : "notes"}`}
              </strong>
              {attention.length > 0 && (
                <>
                  , <strong className="font-medium text-bad">{attention.length} need you</strong>
                </>
              )}
              {active.length > 0 && <>, {active.length} being read</>}.
            </>
          ) : (
            <>{plural(first?.total ?? 0, "note")} in your library.</>
          )
        }
      />

      {nothing ? (
        <div className="grid grid-cols-1 gap-8 lg:grid-cols-[minmax(0,1fr)_21rem]">
          <EmptyState title="Nothing saved yet">
            Save a link, paste text or drop a file. Pith reads it in the background and the finished note appears here.
          </EmptyState>
          <Side lastCapture={lastCapture} />
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-x-10 gap-y-8 lg:grid-cols-[minmax(0,1fr)_21rem]">
          <div className="min-w-0 space-y-8">
            <section aria-label="Needs you">
              <SectionTitle
                count={attention.length}
                actions={
                  attention.length > 0 && (
                    <Link to="/inbox?show=attention" className="text-[13px] text-acc hover:underline">
                      Open in Inbox
                    </Link>
                  )
                }
              >
                Needs you
              </SectionTitle>
              {attention.length === 0 ? (
                <p className="rounded-lg border border-hair bg-panel/50 px-4 py-3 text-[13.5px] text-soft">
                  Nothing failed and nothing is waiting on you.
                </p>
              ) : (
                <div className="space-y-2.5">
                  {attention.slice(0, 4).map((r) => (
                    <AttentionCard key={r.id} row={r} compact />
                  ))}
                  {attention.length > 4 && (
                    <Link to="/inbox?show=attention" className="block text-[13.5px] text-acc hover:underline">
                      {attention.length - 4} more in the Inbox
                    </Link>
                  )}
                </div>
              )}
            </section>

            {active.length > 0 && (
              <section aria-label="Being read">
                <SectionTitle count={active.length}>Being read</SectionTitle>
                <ul className="divide-y divide-hair overflow-hidden rounded-xl border border-line bg-raise">
                  {active.slice(0, 6).map((r) => {
                    const v = statusView(r.status);
                    return (
                      <li key={r.id} className="flex items-center gap-3 px-4 py-2.5">
                        <Loader2 className={r.status === "processing" ? "size-4 animate-spin text-acc" : "size-4 text-mut"} aria-hidden />
                        <span className="min-w-0 flex-1 truncate">{cleanTitle(r.what)}</span>
                        <Chip tone={v.tone}>{v.label}</Chip>
                      </li>
                    );
                  })}
                </ul>
                {active.length > 6 && (
                  <Link to="/inbox?show=working" className="mt-2 block text-[13.5px] text-acc hover:underline">
                    {active.length - 6} more waiting
                  </Link>
                )}
              </section>
            )}

            <section aria-label="New notes">
              <SectionTitle
                count={fresh.length ? fresh.length : undefined}
                actions={
                  <Link to="/library" className="text-[13px] text-acc hover:underline">
                    Open the Library
                  </Link>
                }
              >
                {fresh.length ? "New since your last visit" : "Latest notes"}
              </SectionTitle>
              {shown.length === 0 ? (
                <p className="rounded-lg border border-hair bg-panel/50 px-4 py-3 text-[13.5px] text-soft">
                  No finished notes yet. Items appear here as soon as they are read.
                </p>
              ) : (
                <div className="overflow-hidden rounded-xl border border-line bg-raise">
                  {shown.map((i) => (
                    <NoteRow key={i.id} item={i} />
                  ))}
                </div>
              )}
              {fresh.length > shown.length && (
                <Link to="/library" className="mt-2 block text-[13.5px] text-acc hover:underline">
                  {fresh.length - shown.length} more new notes in the Library
                </Link>
              )}
            </section>

            {(digest.data?.resurfaced.length ?? 0) > 0 && (
              <section aria-label="Worth another look">
                <SectionTitle>Worth another look</SectionTitle>
                <ul className="space-y-1.5">
                  {digest.data?.resurfaced.slice(0, 5).map((r) => (
                    <li key={r.id}>
                      <Link to={`/note/${r.id}`} className="text-[14.5px] hover:text-acc">
                        {cleanTitle(r.title)}
                      </Link>
                      {r.created_at && <span className="ml-2 text-[12.5px] text-mut">saved {when(r.created_at)}</span>}
                    </li>
                  ))}
                </ul>
              </section>
            )}
          </div>
          <Side lastCapture={lastCapture} />
        </div>
      )}
    </div>
  );
}

function TodaySkeleton() {
  return (
    <div aria-busy>
      <Skeleton className="h-8 w-48" />
      <Skeleton className="mt-2 h-4 w-80" />
      <div className="mt-8 space-y-3">
        <Skeleton className="h-24" />
        <Skeleton className="h-40" />
      </div>
    </div>
  );
}

function Side({ lastCapture }: { lastCapture: string | null }) {
  const { saveText, saveFiles } = useCapture();
  const form = useForm<{ text: string; why: string }>({ defaultValues: { text: "", why: "" } });
  const [busy, setBusy] = useState(false);
  const state = useAppState();
  const c = state.data?.capture;
  const models = state.data?.backends ?? [];
  const submit = form.handleSubmit(async (v) => {
    if (!v.text.trim()) return;
    setBusy(true);
    if (await saveText(v.text.trim(), v.why.trim() || undefined)) form.reset();
    setBusy(false);
  });
  return (
    <aside className="space-y-7" aria-label="Capture">
      <section>
        <SectionTitle>Save</SectionTitle>
        <form onSubmit={submit} className="space-y-2">
          <Textarea rows={3} aria-label="Link or text to save" placeholder="Paste a link or text" {...form.register("text")} />
          <Input aria-label="Why are you saving it? (optional)" placeholder="Why? (optional)" {...form.register("why")} />
          <div className="flex items-center gap-2">
            <Button variant="primary" type="submit" loading={busy}>
              Save
            </Button>
            <label className="inline-flex h-9 cursor-pointer items-center rounded-md border border-line bg-raise px-3 text-[13.5px] font-medium text-ink hover:bg-panel focus-within:outline-2 focus-within:outline-acc">
              Attach file
              <input
                type="file"
                multiple
                className="sr-only"
                onChange={(e) => (saveFiles([...(e.target.files ?? [])]), (e.target.value = ""))}
              />
            </label>
          </div>
        </form>
      </section>

      <section aria-label="Capture sources">
        <SectionTitle>Capture sources</SectionTitle>
        <ul className="space-y-3 text-[13.5px]">
          <li className="flex gap-2.5">
            <FolderOpen className="mt-0.5 size-4 shrink-0 text-mut" aria-hidden />
            <span className="min-w-0">
              <span className="font-medium">Drop folder</span>
              {c && c.watch.length > 0 ? (
                c.watch.map((w) => (
                  <span key={w} className="block truncate font-mono text-[12px] text-mut" title={w}>
                    {w}
                  </span>
                ))
              ) : (
                <span className="block text-mut">No folder is watched.</span>
              )}
            </span>
          </li>
          <li className="flex gap-2.5">
            <Globe className="mt-0.5 size-4 shrink-0 text-mut" aria-hidden />
            <span>
              <span className="font-medium">Share endpoint</span>
              <span className="block font-mono text-[12px] text-mut">{c ? `http://${c.http}` : "…"}</span>
            </span>
          </li>
          <li className="flex gap-2.5">
            <Cpu className="mt-0.5 size-4 shrink-0 text-mut" aria-hidden />
            <span>
              <span className="font-medium">Reading with</span>
              <span className="block text-mut">
                {models.length
                  ? models.map((m) => `${m.name}${m.locality === "remote" ? " (remote)" : ""}`).join(", ")
                  : "no model: plain text only"}
              </span>
              {models
                .filter((m) => m.blocked_reason)
                .map((m) => (
                  <span key={m.name} className="block text-warn">
                    {m.name}: {m.blocked_reason}
                  </span>
                ))}
            </span>
          </li>
        </ul>
        <p className="mt-3 text-[13px] text-mut">
          {lastCapture ? <>Last item arrived {when(lastCapture)}. </> : "Nothing has arrived yet. "}
          Pith shows how capture is set up, but cannot tell whether a watcher is running; the arrival time is the real signal.
        </p>
      </section>
    </aside>
  );
}
