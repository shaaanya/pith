/** Timestamps from the API are ISO-8601 UTC strings ("2026-11-17T07:09:02Z"). */
const time = new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" });
const dayMonth = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" });
const dayFull = new Intl.DateTimeFormat(undefined, { weekday: "long", month: "long", day: "numeric" });
const full = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });

const toDate = (iso: string) => new Date(iso);
const startOfDay = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();

export function dayKey(iso: string): string {
  const d = toDate(iso);
  return `${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}`;
}

/** "Today", "Yesterday", "Tuesday, March 4" — used for list group headings. */
export function dayLabel(iso: string, now = new Date()): string {
  const diff = Math.round((startOfDay(now) - startOfDay(toDate(iso))) / 86_400_000);
  if (diff === 0) return "Today";
  if (diff === 1) return "Yesterday";
  return dayFull.format(toDate(iso));
}

/** "just now", "5 min ago", "3:42 PM", "Mar 4". */
export function when(iso: string | null | undefined, now = new Date()): string {
  if (!iso) return "";
  const d = toDate(iso);
  const s = (now.getTime() - d.getTime()) / 1000;
  if (s < 45) return "just now";
  if (s < 3600) return `${Math.max(1, Math.round(s / 60))} min ago`;
  if (startOfDay(now) === startOfDay(d)) return time.format(d);
  return dayMonth.format(d);
}

export const fullDate = (iso: string) => full.format(toDate(iso));

export const plural = (n: number, one: string, many = `${one}s`) => `${n.toLocaleString()} ${n === 1 ? one : many}`;

/** The note title the backend derives is a truncated first line; trim file paths to the name. */
export function cleanTitle(t: string | null | undefined, fallback?: string | null): string {
  const s = (t ?? "").trim();
  // Link notes without a model arrive titled just "Summary": show what they are about instead.
  if ((!s || /^summary$/i.test(s)) && fallback?.trim()) return cleanTitle(fallback.trim().slice(0, 90));
  if (!s) return "Untitled";
  if (s.startsWith("/") && s.includes("/")) return s.split("/").filter(Boolean).pop() ?? s;
  // Derived titles are the first ~80 characters of the text, cut mid-word: end them at a sentence break.
  if (s.length >= 70) {
    const cut = /^(.{12,}?)[.!?:]\s/.exec(s);
    if (cut?.[1]) return cut[1];
  }
  return s;
}

/** Search snippets mark matches as [term]; split into plain/highlight runs. */
export function snippetParts(snippet: string): { text: string; hit: boolean }[] {
  const out: { text: string; hit: boolean }[] = [];
  const re = /\[([^\]]+)\]/g;
  let last = 0;
  for (let m = re.exec(snippet); m; m = re.exec(snippet)) {
    if (m.index > last) out.push({ text: snippet.slice(last, m.index), hit: false });
    out.push({ text: m[1] ?? "", hit: true });
    last = m.index + m[0].length;
  }
  if (last < snippet.length) out.push({ text: snippet.slice(last), hit: false });
  return out;
}

export const hostOf = (url: string | null | undefined) => {
  if (!url) return null;
  try {
    return new URL(url).host.replace(/^www\./, "");
  } catch {
    return null;
  }
};

/** Human wording for the stored error of a failed / waiting item. Never pipeline vocabulary. */
export function explainError(status: string, error: string | null | undefined): { title: string; detail: string; canPaste: boolean } {
  const e = error ?? "";
  if (/no (transcription|ocr|captions? and no transcri\w+) backend|no ocr/i.test(e)) {
    // Backend limit (documented by POST /api/inbox/:id/clarify): pasted text cannot replace a missing transcriber/OCR.
    return {
      title: "Pith has no way to read this yet",
      detail: `${e}. It needs transcription or OCR set up before it can be read.`,
      canPaste: false,
    };
  }
  if (/cannot fix this/i.test(e)) {
    // The backend says so itself: a missing transcriber/OCR or a size limit is not solved by pasting text.
    return { title: "Pasting text will not help", detail: e.replace(/\s*\(pasted text cannot fix this\)/i, ""), canPaste: false };
  }
  if (status === "needs_clarification") {
    return { title: "Needs a little help", detail: e || "Pith could not read this by itself.", canPaste: true };
  }
  if (/403|401|paywall|login|forbidden|blocked/i.test(e)) return { title: "The page is blocked", detail: e, canPaste: true };
  if (/refused|URLError|timed out|timeout|resolve|unreachable|connect/i.test(e))
    return { title: "Could not reach it", detail: e, canPaste: true };
  if (/too large|limit/i.test(e)) return { title: "Over the size limit", detail: e, canPaste: false };
  return { title: "Could not be read", detail: e || "No reason was recorded.", canPaste: true };
}
