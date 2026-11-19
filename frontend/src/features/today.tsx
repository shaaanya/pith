import { Loader2, TriangleAlert } from "lucide-react";
import { useEffect, useMemo } from "react";
import { Link } from "react-router";
import { AttentionLine } from "@/components/attention";
import { Chip, EmptyState, ErrorState, Skeleton } from "@/components/ui";
import { cleanTitle, fullDate, plural } from "@/lib/format";
import { isNew, lastVisit } from "@/lib/local";
import { useAppState, useInbox, useLibrary, useRecentlyOpened, useResurface, useTopics } from "@/lib/queries";
import { useShelfData } from "@/lib/shelf-data";
import { toPlaced } from "@/lib/shelves";
import { CaptureBox, HomeSearch, JumpBackIn, Rediscover, Remembered, Topics } from "./home/panels";
import { UpNext, upNextShown } from "./home/worth-doing";
import { statusView } from "./inbox";

const greeting = () => {
  const h = new Date().getHours();
  return h < 5 ? "Late night" : h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
};

/**
 * Home answers four questions in order: is anything broken (only when it is), what did I mean to do (Up next),
 * what have I forgotten (Worth revisiting), what was just saved (Recently saved). A section with nothing to say is
 * not drawn, so the page is as useful with 11 notes in one shelf as with thousands. Shelves live in the sidebar, not here.
 * Layout follows the width of the page (container queries), not the window: two columns when there is room, one ordered stack when not.
 */
export function Today() {
  const state = useAppState();
  const busy = (state.data?.counts.pending ?? 0) + (state.data?.counts.processing ?? 0) + (state.data?.counts.new ?? 0) > 0;
  const lib = useLibrary({}, busy);
  const first = lib.data?.pages[0];
  const inbox = useInbox(false);
  const data = useShelfData();
  const resurfaced = useResurface();
  const opened = useRecentlyOpened(5);
  const topics = useTopics();

  useEffect(() => {
    document.title = "Home · Pith";
  }, []);

  const items = useMemo(() => lib.data?.pages.flatMap((p) => p.items) ?? [], [lib.data]);
  const fresh = items.filter((i) => isNew(i.created_at));
  const attention = first?.attention ?? [];
  const active = first?.active ?? [];
  const lastCapture = useMemo(
    () => (inbox.data ?? []).reduce<string | null>((mx, r) => (!mx || r.submitted_at > mx ? r.submitted_at : mx), null),
    [inbox.data],
  );
  const continueList = (opened.data?.items ?? [])
    .map(toPlaced)
    .map((p) => ({ id: p.item.id, title: cleanTitle(p.item.title, p.item.lead ?? p.item.host) }));
  const blocked = (state.data?.backends ?? []).filter((b) => b.blocked_reason);

  if (lib.isPending) return <HomeSkeleton />;
  if (lib.isError) return <ErrorState error={lib.error} retry={() => void lib.refetch()} />;

  const total = first?.total ?? 0;
  const nothing = total === 0 && attention.length === 0 && active.length === 0;
  const hasUp = data.open.length > 0;
  const shown = upNextShown(data);
  const back = resurfaced.data && { ...resurfaced.data, items: resurfaced.data.items.filter((r) => !shown.has(r.id)) };
  const hasBack = (back?.items ?? []).some((r) => data.byId.has(r.id));
  const hasTopics = (topics.data ?? []).some((t) => t.n > 1);
  const hasSide = hasUp || hasBack || continueList.length > 0 || hasTopics;
  const newCount = lastVisit ? fresh.length : null;

  return (
    <div className="enter @container">
      <header className="flex flex-wrap items-end justify-between gap-x-8 gap-y-4 pb-6">
        <div className="min-w-0">
          <h1 className="font-serif text-[30px] leading-tight font-semibold tracking-[-0.01em]">{greeting()}</h1>
          <p className="mt-1 text-[14px] text-mut" aria-live="polite">
            {nothing ? (
              "Nothing saved yet."
            ) : lastVisit ? (
              <>
                {plural(total, "note")} remembered. Since you were last here ({fullDate(lastVisit)}):{" "}
                <strong className="font-medium text-ink">
                  {newCount === 0 ? "nothing new" : `${newCount}${lib.hasNextPage && fresh.length >= items.length ? "+" : ""} new`}
                </strong>
                .
              </>
            ) : (
              <>{plural(total, "note")} remembered so far.</>
            )}
          </p>
        </div>
        {!nothing && <HomeSearch />}
      </header>

      {/* Only what needs you or is happening right now. Nothing here when all is well. */}
      {(attention.length > 0 || active.length > 0 || blocked.length > 0) && (
        <section aria-label="Needs attention" className="mb-8 space-y-3">
          {attention.length > 0 && (
            <div>
              <ul className="divide-y divide-hair rounded-lg border border-bad/30 bg-bad-tint/50">
                {attention.slice(0, 3).map((r) => (
                  <AttentionLine key={r.id} row={r} />
                ))}
              </ul>
              {attention.length > 3 && (
                <Link to="/inbox?show=attention" className="mt-1.5 inline-flex h-8 items-center text-[13px] text-acc hover:underline">
                  {attention.length - 3} more in the Inbox
                </Link>
              )}
            </div>
          )}
          {active.length > 0 && (
            <ul className="divide-y divide-hair">
              {active.slice(0, 3).map((r) => {
                const v = statusView(r.status);
                return (
                  <li key={r.id} className="flex items-center gap-3 py-1.5 text-[13.5px]">
                    <Loader2 className={r.status === "processing" ? "size-4 animate-spin text-acc" : "size-4 text-mut"} aria-hidden />
                    <span className="min-w-0 flex-1 truncate">{r.what}</span>
                    <Chip tone={v.tone}>{v.label}</Chip>
                  </li>
                );
              })}
            </ul>
          )}
          {blocked.length > 0 && (
            <Link to="/settings" className="inline-flex min-h-8 items-center gap-2 text-[13.5px] text-warn hover:underline" title={blocked[0]?.blocked_reason ?? undefined}>
              <TriangleAlert className="size-4" aria-hidden />
              {blocked.length === 1 ? `${blocked[0]?.name} is unavailable: new saves wait until it is back` : `${blocked.length} model backends are unavailable`}
            </Link>
          )}
        </section>
      )}

      {nothing ? (
        <div className="mx-auto max-w-xl space-y-8">
          <EmptyState title="Nothing saved yet">
            Share a link or file from your phone, drop it in the watched folder, or paste it here. Pith reads it in the background and what
            it learned shows up on this page.
          </EmptyState>
          <CaptureBox lastCapture={lastCapture} />
        </div>
      ) : (
        <div
          className={
            hasSide
              ? "grid grid-cols-1 gap-x-12 gap-y-9 @4xl:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]"
              : "grid max-w-3xl grid-cols-1 gap-y-9"
          }
        >
          {/* On a narrow page the columns dissolve and `order` sets one stack: intentions, rediscovery, recent, topics. */}
          <div className="grid min-w-0 content-start gap-9 @max-4xl:contents">
            {hasUp ? (
              <UpNext data={data} className="@max-4xl:order-1" />
            ) : (
              <Remembered items={items} data={data} hasMore={!!lib.hasNextPage} className="@max-4xl:order-3" />
            )}
          </div>
          <div className="grid min-w-0 content-start gap-9 @max-4xl:contents">
            <Rediscover data={data} resurfaced={back} className={hasBack ? "@max-4xl:order-2" : "hidden"} />
            {hasUp && <Remembered items={items} data={data} hasMore={!!lib.hasNextPage} className="@max-4xl:order-3" />}
            <JumpBackIn list={continueList} className="@max-4xl:order-4" />
            <Topics className="@max-4xl:order-5" />
          </div>
        </div>
      )}
    </div>
  );
}

function HomeSkeleton() {
  return (
    <div aria-busy>
      <Skeleton className="h-9 w-56" />
      <Skeleton className="mt-2 h-4 w-80" />
      <div className="mt-8 space-y-3">
        <Skeleton className="h-24" />
        <Skeleton className="h-40" />
      </div>
    </div>
  );
}
