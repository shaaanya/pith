/** TanStack Query hooks: one per endpoint, with targeted invalidation. Polling only while work is active. */
import { keepPreviousData, useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { qs, request } from "./api";
import * as S from "./schemas";

export const keys = {
  state: ["state"] as const,
  library: (f: { type?: string; topic?: string }) => ["library", f] as const,
  inbox: ["inbox"] as const,
  inboxItem: (id: string) => ["inbox", id] as const,
  item: (id: string) => ["item", id] as const,
  topics: ["topics"] as const,
  search: (q: string, f: object) => ["search", q, f] as const,
  duplicates: ["duplicates"] as const,
  digest: ["digest"] as const,
  config: ["config"] as const,
  privacy: ["privacy"] as const,
};

const busy = (s?: S.AppState) => !!s && (s.counts.pending ?? 0) + (s.counts.processing ?? 0) + (s.counts.new ?? 0) > 0;

export function useAppState() {
  return useQuery({
    queryKey: keys.state,
    queryFn: ({ signal }) => request(S.AppState, "GET", "/api/state", undefined, signal),
    refetchInterval: (q) => (busy(q.state.data) ? 2500 : 20000),
  });
}

/** Library pages: newest first, cursor = the `next` value. The first page also carries active/attention. */
export function useLibrary(filter: { type?: string; topic?: string }, polling: boolean) {
  return useInfiniteQuery({
    queryKey: keys.library(filter),
    initialPageParam: "" as string,
    queryFn: ({ pageParam, signal }) =>
      request(S.LibraryPage, "GET", `/api/library${qs({ ...filter, before: pageParam, limit: 50 })}`, undefined, signal),
    getNextPageParam: (last) => last.next ?? undefined,
    refetchInterval: polling ? 2500 : false,
    placeholderData: keepPreviousData,
  });
}

/**
 * Every note, light fields only, paged in the background (the API caps a page at 100). Shelves, counts and
 * resurfacing are derived from this in the browser. Capped at 3,000 notes; `truncated` says so honestly.
 */
const INDEX_PAGES = 30;
export const useNotesIndex = () =>
  useQuery({
    queryKey: ["library", "index"] as const,
    staleTime: 60_000,
    queryFn: async ({ signal }) => {
      const items: S.LibraryItem[] = [];
      let before = "";
      let total = 0;
      for (let i = 0; i < INDEX_PAGES; i++) {
        const p = await request(S.LibraryPage, "GET", `/api/library${qs({ before, limit: 100 })}`, undefined, signal);
        total = p.total;
        items.push(...p.items);
        if (!p.next) return { items, total, truncated: false };
        before = p.next;
      }
      return { items, total, truncated: true };
    },
  });

export const useTopics = () =>
  useQuery({
    queryKey: keys.topics,
    queryFn: ({ signal }) => request(S.Topics, "GET", "/api/topics", undefined, signal),
    staleTime: 30_000,
  });

export function useInbox(polling: boolean) {
  return useQuery({
    queryKey: keys.inbox,
    queryFn: ({ signal }) => request(S.InboxList, "GET", "/api/inbox", undefined, signal),
    refetchInterval: polling ? 2500 : 20000,
  });
}

export const useInboxDetail = (id: string | null) =>
  useQuery({
    queryKey: keys.inboxItem(id ?? ""),
    queryFn: ({ signal }) => request(S.InboxDetail, "GET", `/api/inbox/${id}`, undefined, signal),
    enabled: !!id,
  });

export const useItem = (id: string) =>
  useQuery({
    queryKey: keys.item(id),
    queryFn: ({ signal }) => request(S.ItemDetail, "GET", `/api/items/${id}`, undefined, signal),
    enabled: !!id,
  });

export const useDigest = () =>
  useQuery({
    queryKey: keys.digest,
    queryFn: ({ signal }) => request(S.Digest, "GET", "/api/digest", undefined, signal),
    staleTime: 60_000,
  });

export const useDuplicates = (enabled: boolean) =>
  useQuery({
    queryKey: keys.duplicates,
    queryFn: ({ signal }) => request(S.Duplicates, "GET", "/api/duplicates", undefined, signal),
    enabled,
  });

export function useSearch(q: string, filters: { kind?: string; topic?: string; provenance?: string }) {
  const term = q.trim();
  return useQuery({
    queryKey: keys.search(term, filters),
    queryFn: ({ signal }) => request(S.SearchResult, "GET", `/api/search${qs({ q: term, ...filters })}`, undefined, signal),
    enabled: term.length > 1,
    placeholderData: keepPreviousData,
    staleTime: 15_000,
  });
}

export const usePrivacy = () =>
  useQuery({ queryKey: keys.privacy, queryFn: ({ signal }) => request(S.Privacy, "GET", "/api/privacy", undefined, signal) });
export const useConfig = () =>
  useQuery({ queryKey: keys.config, queryFn: ({ signal }) => request(S.Config, "GET", "/api/config", undefined, signal) });

// ---- mutations
function useInvalidating<V, R>(fn: (v: V) => Promise<R>, ...prefixes: (readonly unknown[])[]) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      for (const p of prefixes) void qc.invalidateQueries({ queryKey: p });
    },
  });
}

const refresh = [keys.state, ["library"], keys.inbox] as const;

export const useSubmit = () =>
  useInvalidating(
    (v: { text?: string; file?: File; context?: string }) => {
      if (v.file) {
        const f = new FormData();
        f.set("file", v.file, v.file.name || "pasted-file");
        if (v.context) f.set("context", v.context);
        return request(S.Submitted, "POST", "/api/inbox", f);
      }
      return request(S.Submitted, "POST", "/api/inbox", { text: v.text, ...(v.context ? { context: v.context } : {}) });
    },
    ...refresh,
  );

export const useRetry = () => useInvalidating((id: string) => request(S.Ok, "POST", `/api/inbox/${id}/retry`, {}), ...refresh);

export const useClarify = () =>
  useInvalidating((v: { id: string; text: string }) => request(S.Ok, "POST", `/api/inbox/${v.id}/clarify`, { text: v.text }), ...refresh);

export const useReprocess = () => useInvalidating((id: string) => request(S.Ok, "POST", `/api/items/${id}/reprocess`, {}), ...refresh);

export const useDeleteItem = () =>
  useInvalidating((id: string) => request(S.Ok, "DELETE", `/api/items/${id}`), ["library"], keys.state, keys.topics, keys.duplicates, [
    "desk",
  ]);

export function useUpdateItem(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { title?: string; body?: string }) => request(S.ItemDetail, "PATCH", `/api/items/${id}`, v),
    onSuccess: (data) => {
      qc.setQueryData(keys.item(id), data);
      void qc.invalidateQueries({ queryKey: ["library"] });
      void qc.invalidateQueries({ queryKey: ["desk"] });
    },
  });
}

export const useAsk = () => useMutation({ mutationFn: (q: string) => request(S.Answer, "POST", "/api/ask", { q }) });

export const useSaveConfig = () =>
  useInvalidating(
    (v: { backends: Record<string, Record<string, unknown>>; tasks: Record<string, string[]>; allow_remote: boolean }) =>
      request(S.Config, "POST", "/api/config", v),
    keys.config,
    keys.state,
    keys.privacy,
  );

export const detectProviders = () => request(S.Providers, "GET", "/api/providers/detect");
export const detectModels = (baseUrl: string) => request(S.Models, "GET", `/api/models${qs({ base_url: baseUrl })}`);

// ---- shelves, resurfacing, entries, recently opened
export const useShelves = () =>
  useQuery({
    queryKey: ["shelves"] as const,
    queryFn: ({ signal }) => request(S.Shelves, "GET", "/api/shelves", undefined, signal),
    staleTime: 10_000,
  });

export const useResurface = () =>
  useQuery({
    queryKey: ["resurface"] as const,
    queryFn: ({ signal }) => request(S.Resurfaced, "GET", "/api/resurface", undefined, signal),
    staleTime: 30_000,
  });

export const useEntries = (filter: { shelf?: string; done?: "0" | "1" }) =>
  useQuery({
    queryKey: ["entries", filter] as const,
    queryFn: ({ signal }) => request(S.EntryRows, "GET", `/api/entries${qs(filter)}`, undefined, signal),
    staleTime: 10_000,
  });

/** Notes you opened most recently, newest first. */
export const useRecentlyOpened = (limit = 6) =>
  useQuery({
    queryKey: ["library", "viewed", limit] as const,
    queryFn: ({ signal }) => request(S.LibraryPage, "GET", `/api/library${qs({ viewed: "1", limit })}`, undefined, signal),
    staleTime: 10_000,
  });

export const useDesk = () =>
  useQuery({
    queryKey: ["desk"],
    staleTime: 0,
    queryFn: ({ signal }) => request(S.Desk, "GET", "/api/desk", undefined, signal),
  });

export function useSaveDesk() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (desk: S.Desk) =>
      request(S.Desk, "PATCH", "/api/desk", {
        revision: desk.revision,
        groups: desk.groups.map(({ items: _items, ...group }) => group),
      }),
    onSuccess: (data) => qc.setQueryData(["desk"], data),
  });
}
