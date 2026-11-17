import { ExternalLink, Search as SearchIcon, Sparkles } from "lucide-react";
import { Fragment, useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { Button, Chip, EmptyState, ErrorState, Kbd, PageHeader, Select, Skeleton, Spinner } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { cleanTitle, hostOf, snippetParts } from "@/lib/format";
import { read, write } from "@/lib/local";
import { useAsk, useSearch, useTopics } from "@/lib/queries";
import type { Answer, SearchHit } from "@/lib/schemas";
import { cn, safeHref } from "@/lib/utils";

const RECENT = "pith.recent";
const loadRecent = (): string[] => {
  try {
    const v: unknown = JSON.parse(read(RECENT) ?? "[]");
    return Array.isArray(v) ? v.filter((x): x is string => typeof x === "string").slice(0, 6) : [];
  } catch {
    return [];
  }
};

export function Search() {
  const [params, setParams] = useSearchParams();
  const urlQ = params.get("q") ?? "";
  const kind = params.get("kind") ?? "";
  const topic = params.get("topic") ?? "";
  const [text, setText] = useState(urlQ);
  const [recent, setRecent] = useState(loadRecent);
  const input = useRef<HTMLInputElement>(null);
  const topics = useTopics();
  const ask = useAsk();

  useEffect(() => {
    document.title = "Search & Ask · Pith";
    if (params.get("focus")) input.current?.focus();
  }, [params]);

  // Debounce typing into the URL (the URL is the source of truth, so searches are shareable and back-able).
  useEffect(() => {
    if (text === urlQ) return;
    const t = window.setTimeout(() => {
      setParams(
        (p) => {
          const n = new URLSearchParams(p);
          if (text.trim()) n.set("q", text);
          else n.delete("q");
          n.delete("focus");
          return n;
        },
        { replace: true },
      );
    }, 250);
    return () => window.clearTimeout(t);
  }, [text, urlQ, setParams]);
  useEffect(() => setText(urlQ), [urlQ]);

  const q = urlQ.trim();
  const res = useSearch(q, { kind: kind || undefined, topic: topic || undefined });

  const remember = (v: string) => {
    const next = [v, ...recent.filter((x) => x !== v)].slice(0, 6);
    setRecent(next);
    write(RECENT, JSON.stringify(next));
  };
  const doAsk = () => {
    if (!text.trim() || ask.isPending) return;
    remember(text.trim());
    ask.mutate(text.trim());
  };
  const setFilter = (k: string, v: string) =>
    setParams(
      (p) => {
        const n = new URLSearchParams(p);
        if (v) n.set(k, v);
        else n.delete(k);
        return n;
      },
      { replace: true },
    );

  return (
    <div className="enter mx-auto max-w-4xl">
      <PageHeader title="Search & Ask" sub="Find the exact passage, or ask a question across everything you saved." />

      <form
        role="search"
        className="sticky top-12 z-20 -mx-1 bg-paper/95 px-1 pb-3 backdrop-blur md:top-0 md:pt-1"
        onSubmit={(e) => {
          e.preventDefault();
          if (text.trim()) remember(text.trim());
        }}
      >
        <div className="relative">
          <SearchIcon className="pointer-events-none absolute top-1/2 left-3.5 size-[18px] -translate-y-1/2 text-mut" aria-hidden />
          <input
            ref={input}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
                e.preventDefault();
                doAsk();
              }
            }}
            type="search"
            enterKeyHint="search"
            autoComplete="off"
            aria-label="Search your notes or ask a question"
            placeholder="Search a word, a tool, a number — or ask a question"
            className="h-12 w-full rounded-xl border border-line bg-raise pr-4 pl-11 text-[16px] placeholder:text-mut hover:border-mut focus-visible:border-acc focus-visible:ring-2 focus-visible:ring-acc/30 focus-visible:outline-none"
          />
        </div>
        <div className="mt-2.5 flex flex-wrap items-center gap-2">
          <Select
            aria-label="Search in"
            value={kind}
            onChange={(e) => setFilter("kind", e.target.value)}
            className="h-8 w-auto text-[13px]"
          >
            <option value="">Notes and source passages</option>
            <option value="note">Notes only</option>
            <option value="segment">Source passages only</option>
          </Select>
          <Select
            aria-label="Topic"
            value={topic}
            onChange={(e) => setFilter("topic", e.target.value)}
            className="h-8 w-auto max-w-48 text-[13px]"
          >
            <option value="">Any topic</option>
            {topics.data?.map((t) => (
              <option key={t.name} value={t.name}>
                {t.name} ({t.n})
              </option>
            ))}
          </Select>
          <Button variant="primary" size="sm" className="ml-auto" onClick={doAsk} disabled={!text.trim()} loading={ask.isPending}>
            <Sparkles className="size-3.5" aria-hidden /> Ask this question{" "}
            <span className="hidden opacity-75 sm:inline">
              <Kbd>⌘↵</Kbd>
            </span>
          </Button>
        </div>
      </form>

      {(ask.isPending || ask.isError || ask.data) && (
        <section aria-label="Answer" className="mb-8">
          <h2 className="mb-2 flex items-center gap-2 text-[12px] font-semibold tracking-[0.06em] text-acc uppercase">
            <Sparkles className="size-3.5" aria-hidden /> Answer
          </h2>
          {ask.isPending && (
            <div className="rounded-xl border border-acc/30 bg-acc-tint/40 p-5">
              <Spinner label="Reading your notes" />
              <p className="mt-2 text-[13.5px] text-mut">Reading your notes and writing an answer. A local model can take a minute.</p>
            </div>
          )}
          {ask.isError && <ErrorState error={ask.error instanceof ApiError ? ask.error : new Error("Could not answer.")} retry={doAsk} />}
          {ask.data && <AnswerCard a={ask.data} />}
        </section>
      )}

      <section aria-label="Search results">
        {q.length > 1 && (
          <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="text-[12px] font-semibold tracking-[0.06em] text-mut uppercase">
              Passages{res.data ? <span className="ml-2 font-normal tracking-normal tabular-nums">{res.data.hits.length}</span> : null}
            </h2>
            {res.data && (
              <span className="text-[12.5px] text-mut">{res.data.mode === "hybrid" ? "Keywords and meaning" : "Keyword match only"}</span>
            )}
          </div>
        )}
        {q.length <= 1 && <Idle recent={recent} pick={(v) => setText(v)} />}
        {q.length > 1 && res.isPending && <Results skeleton />}
        {res.isError && <ErrorState error={res.error} retry={() => void res.refetch()} />}
        {res.data && (
          <>
            {res.data.warnings.map((w) => (
              <p key={w} className="mb-2 rounded-md bg-warn-tint px-3 py-2 text-[13px] text-warn">
                {w}
              </p>
            ))}
            {res.data.hits.length === 0 ? (
              <EmptyState title={`Nothing found for “${q}”`}>
                Try fewer or different words{kind || topic ? ", or remove a filter" : ""}. A single mention inside a long video or PDF is
                searched too.
                {res.data.mode === "fts" && " Matching is by keyword here, so a related word will not match."}
              </EmptyState>
            ) : (
              <Results hits={res.data.hits} fetching={res.isFetching} />
            )}
          </>
        )}
      </section>
    </div>
  );
}

function Idle({ recent, pick }: { recent: string[]; pick: (v: string) => void }) {
  return (
    <div className="py-6">
      {recent.length > 0 ? (
        <>
          <h2 className="mb-2 text-[12px] font-semibold tracking-[0.06em] text-mut uppercase">Recent</h2>
          <ul className="flex flex-wrap gap-2">
            {recent.map((r) => (
              <li key={r}>
                <button
                  type="button"
                  onClick={() => pick(r)}
                  className="rounded-full border border-line bg-raise px-3 py-1 text-[13.5px] text-soft hover:border-acc hover:text-acc"
                >
                  {r}
                </button>
              </li>
            ))}
          </ul>
        </>
      ) : null}
      <div className="mt-6 grid gap-4 text-[13.5px] text-soft sm:grid-cols-2">
        <p>
          <strong className="text-ink">Search</strong> finds passages as you type, including a single mention inside a long video, PDF or
          article.
        </p>
        <p>
          <strong className="text-ink">Ask</strong> writes a short answer from your saved notes and cites each source. Nothing is answered
          from outside your library.
        </p>
      </div>
    </div>
  );
}

function Results({ hits, fetching, skeleton }: { hits?: SearchHit[]; fetching?: boolean; skeleton?: boolean }) {
  if (skeleton)
    return (
      <div aria-busy className="space-y-4">
        {[0, 1, 2, 3].map((i) => (
          <div key={i}>
            <Skeleton className="h-4 w-1/3" />
            <Skeleton className="mt-2 h-4 w-full" />
          </div>
        ))}
      </div>
    );
  return (
    <ul
      className={cn(
        "divide-y divide-hair overflow-hidden rounded-xl border border-line bg-raise transition-opacity",
        fetching && "opacity-70",
      )}
      aria-live="polite"
    >
      {hits?.map((h, i) => (
        <Hit key={`${h.item_id ?? h.segment_id}-${i}`} h={h} />
      ))}
    </ul>
  );
}

function Hit({ h }: { h: SearchHit }) {
  const target = h.note_id ?? h.item_id;
  const src = safeHref(h.source_url);
  const title = cleanTitle(
    h.title,
    snippetParts(h.snippet)
      .map((p) => p.text)
      .join("")
      .slice(0, 80),
  );
  return (
    <li className="relative px-4 py-3 hover:bg-panel/60">
      <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[12.5px] text-mut">
        <Chip tone={h.kind === "segment" ? "outline" : "neutral"}>{h.kind === "segment" ? "From the source" : "Note"}</Chip>
        {h.locator && !h.locator.startsWith("char=") && <span className="font-mono">{h.locator}</span>}
        {hostOf(src) && <span>{hostOf(src)}</span>}
      </p>
      <h3 className="mt-1 leading-snug font-medium">
        {target ? (
          <Link to={`/note/${target}`} className="after:absolute after:inset-0 after:content-[''] hover:text-acc">
            {title}
          </Link>
        ) : (
          title
        )}
      </h3>
      <p className="mt-1 font-serif text-[15px] leading-relaxed text-soft">
        {snippetParts(h.snippet).map((p, i) =>
          p.hit ? (
            <mark key={i} className="hit">
              {p.text}
            </mark>
          ) : (
            <Fragment key={i}>{p.text}</Fragment>
          ),
        )}
      </p>
      {src && (
        <a
          href={src}
          target="_blank"
          rel="noopener noreferrer"
          className="relative z-10 mt-1.5 inline-flex items-center gap-1 text-[12.5px] text-mut hover:text-acc"
        >
          Original <ExternalLink className="size-3" aria-hidden />
        </a>
      )}
    </li>
  );
}

function AnswerCard({ a }: { a: Answer }) {
  const answered = a.mode === "answer" && !!a.interpretation;
  const used = new Set(a.citations);
  const body = (a.interpretation ?? "").split(/(\[\d+\])/g);
  return (
    <div className="rounded-xl border border-acc/30 bg-acc-tint/40 p-5">
      {answered ? (
        <>
          <p className="font-serif text-[17.5px] leading-relaxed whitespace-pre-line">
            {body.map((part, i) => {
              const m = /^\[(\d+)\]$/.exec(part);
              return m ? (
                <a
                  key={i}
                  href={`#excerpt-${m[1]}`}
                  className="mx-0.5 rounded bg-raise px-1 align-super font-sans text-[11px] font-semibold text-acc no-underline hover:underline"
                  aria-label={`Source ${m[1]}`}
                >
                  {m[1]}
                </a>
              ) : (
                <Fragment key={i}>{part}</Fragment>
              );
            })}
          </p>
          <p className="mt-3 text-[12.5px] text-mut">
            Written by {a.generated_by ?? "a model"} from the {a.retrieved.length} passages below. Check the sources before relying on it.
          </p>
          {a.invalid_citations.length > 0 && (
            <p className="mt-2 rounded-md bg-warn-tint px-3 py-2 text-[13px] text-warn">
              The answer pointed to sources that do not exist ({a.invalid_citations.join(", ")}). Ignore those references.
            </p>
          )}
        </>
      ) : (
        <div>
          <p className="font-medium">No answer was written.</p>
          <p className="mt-0.5 text-[13.5px] text-soft">
            {a.message || "No model is set up to answer, or it could not. These are the most relevant passages from your notes."}
          </p>
        </div>
      )}
      {a.warnings.map((w) => (
        <p key={w} className="mt-2 text-[13px] text-warn">
          {w}
        </p>
      ))}
      {a.retrieved.length > 0 && (
        <ol className="mt-4 space-y-2" aria-label="Sources">
          {a.retrieved.map((e) => {
            const link = safeHref(e.deep_link ?? e.url);
            const target = e.note_id ?? e.item_id;
            return (
              <li
                key={e.n}
                id={`excerpt-${e.n}`}
                className={cn(
                  "scroll-mt-28 rounded-lg border bg-raise p-3 target:ring-2 target:ring-acc",
                  used.has(e.n) ? "border-acc/40" : "border-line",
                )}
              >
                <p className="flex flex-wrap items-center gap-x-2 text-[13px]">
                  <span className="grid size-5 place-items-center rounded bg-acc-tint text-[11px] font-semibold text-acc">{e.n}</span>
                  {target ? (
                    <Link to={`/note/${target}`} className="font-medium hover:text-acc">
                      {cleanTitle(e.title, e.text)}
                    </Link>
                  ) : (
                    <span className="font-medium">{cleanTitle(e.title, e.text)}</span>
                  )}
                  {e.locator && !e.locator.startsWith("char=") && <span className="font-mono text-[12px] text-mut">{e.locator}</span>}
                  {link && (
                    <a
                      href={link}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="ml-auto inline-flex items-center gap-1 text-[12.5px] text-mut hover:text-acc"
                    >
                      Open at source <ExternalLink className="size-3" aria-hidden />
                    </a>
                  )}
                </p>
                <p className="mt-1.5 line-clamp-4 font-serif text-[14.5px] leading-relaxed text-soft">{e.text}</p>
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}
