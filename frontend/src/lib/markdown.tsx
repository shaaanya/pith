/**
 * Small, safe Markdown → React renderer for note bodies. Builds elements (never HTML strings),
 * so there is no injection sink; links are limited to http(s). Supports what Pith notes use:
 * headings, ordered/unordered lists, fenced code, blockquotes, bold, italic, inline code, links.
 */
import { Fragment, type ReactNode } from "react";
import { safeHref } from "./utils";

export type Block =
  | { t: "h"; level: number; text: string }
  | { t: "p"; text: string }
  | { t: "ul" | "ol"; items: string[] }
  | { t: "code"; text: string }
  | { t: "quote"; text: string };

const BULLET = /^\s*[-*•]\s+(.*)$/;
const NUMBERED = /^\s*\d+[.)]\s+(.*)$/;

export function parseBlocks(src: string): Block[] {
  const lines = src.replace(/\r\n?/g, "\n").split("\n");
  const out: Block[] = [];
  let para: string[] = [];
  const flush = () => {
    if (para.length) out.push({ t: "p", text: para.join(" ") });
    para = [];
  };
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i] ?? "";
    if (line.trimStart().startsWith("```")) {
      flush();
      const code: string[] = [];
      for (i++; i < lines.length && !(lines[i] ?? "").trimStart().startsWith("```"); i++) code.push(lines[i] ?? "");
      out.push({ t: "code", text: code.join("\n") });
      continue;
    }
    if (!line.trim()) {
      flush();
      continue;
    }
    const h = /^(#{1,4})\s+(.*)$/.exec(line);
    if (h) {
      flush();
      out.push({ t: "h", level: (h[1] ?? "#").length, text: h[2] ?? "" });
      continue;
    }
    const kind = BULLET.test(line) ? "ul" : NUMBERED.test(line) ? "ol" : null;
    if (kind) {
      flush();
      const re = kind === "ul" ? BULLET : NUMBERED;
      const items: string[] = [];
      for (; i < lines.length; i++) {
        const m = re.exec(lines[i] ?? "");
        if (m) items.push(m[1] ?? "");
        else if (/^\s{2,}\S/.test(lines[i] ?? "") && items.length) items[items.length - 1] += " " + (lines[i] ?? "").trim();
        else break;
      }
      i--;
      out.push({ t: kind, items });
      continue;
    }
    if (line.startsWith(">")) {
      flush();
      out.push({ t: "quote", text: line.replace(/^>\s?/, "") });
      continue;
    }
    para.push(line.trim());
  }
  flush();
  return out;
}

const INLINE_RE = /(`[^`]+`)|(\*\*[^*]+\*\*)|(\[[^\]]+\]\([^)\s]+\))|(\*[^*\s][^*]*\*)|(https?:\/\/[^\s)<>]+)/;

export function inline(text: string): ReactNode[] {
  const INLINE = new RegExp(INLINE_RE.source, "g"); // per call: recursion must not share lastIndex
  const out: ReactNode[] = [];
  let last = 0;
  let k = 0;
  for (let m = INLINE.exec(text); m; m = INLINE.exec(text)) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const tok = m[0];
    if (m[1]) out.push(<code key={k++}>{tok.slice(1, -1)}</code>);
    else if (m[2]) out.push(<strong key={k++}>{inline(tok.slice(2, -2))}</strong>);
    else if (m[3]) {
      const mm = /^\[([^\]]+)\]\(([^)\s]+)\)$/.exec(tok);
      const href = safeHref(mm?.[2]);
      out.push(
        href ? (
          <a key={k++} href={href} target="_blank" rel="noopener noreferrer">
            {mm?.[1]}
          </a>
        ) : (
          <Fragment key={k++}>{mm?.[1]}</Fragment>
        ),
      );
    } else if (m[4]) out.push(<em key={k++}>{tok.slice(1, -1)}</em>);
    else {
      const trimmed = tok.replace(/[.,;:!?]+$/, "");
      const href = safeHref(trimmed);
      out.push(
        href ? (
          <a key={k++} href={href} target="_blank" rel="noopener noreferrer">
            {trimmed}
          </a>
        ) : (
          tok
        ),
      );
      if (trimmed.length < tok.length) out.push(tok.slice(trimmed.length));
    }
    last = m.index + tok.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export function Markdown({ source, className = "prose-pith" }: { source: string; className?: string }) {
  const blocks = parseBlocks(source);
  return (
    <div className={className}>
      {blocks.map((b, i) => {
        switch (b.t) {
          case "h":
            return b.level <= 2 ? <h2 key={i}>{inline(b.text)}</h2> : <h3 key={i}>{inline(b.text)}</h3>;
          case "p":
            return <p key={i}>{inline(b.text)}</p>;
          case "ul":
            return (
              <ul key={i}>
                {b.items.map((x, j) => (
                  <li key={j}>{inline(x)}</li>
                ))}
              </ul>
            );
          case "ol":
            return (
              <ol key={i}>
                {b.items.map((x, j) => (
                  <li key={j}>{inline(x)}</li>
                ))}
              </ol>
            );
          case "code":
            return (
              <pre key={i}>
                <code>{b.text}</code>
              </pre>
            );
          case "quote":
            return <blockquote key={i}>{inline(b.text)}</blockquote>;
        }
      })}
    </div>
  );
}

/** Plain-text export used by "Copy as Markdown". */
export const asMarkdown = (title: string, body: string) => `# ${title}\n\n${body.trim()}\n`;
