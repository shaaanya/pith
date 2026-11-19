import { useLayoutEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  Copy,
  ExternalLink,
  BookOpen,
  AlertCircle,
} from "lucide-react";
import type { Item } from "./data";

export function Reader({
  item,
  items,
  related,
  onBack,
  canBack,
  announce,
  scrollPosition,
}: {
  item: Item;
  items: Item[];
  related: (id: string, scroll: number) => void;
  onBack: () => void;
  canBack: boolean;
  announce: (s: string) => void;
  scrollPosition: number;
}) {
  const body = useRef<HTMLDivElement>(null);
  const [copyError, setCopyError] = useState(false);
  const [copyStatus, setCopyStatus] = useState("");
  useLayoutEffect(() => {
    body.current!.scrollTop = scrollPosition;
    setCopyError(false);
  }, [item.id, scrollPosition]);
  async function copy(text: string) {
    try {
      await navigator.clipboard.writeText(text);
      announce("Copied to clipboard");
      setCopyStatus("Copied to clipboard");
      setCopyError(false);
    } catch {
      setCopyError(true);
      setCopyStatus("Copy was blocked");
      announce("Copy was blocked. You can select and copy the text instead.");
    }
  }
  return (
    <>
      <div ref={body} className="reader-content modal-body">
        <div className="reading-column">
          {canBack && (
            <button className="quiet-button back-link" onClick={onBack}>
              <ArrowLeft size={16} />
              Back to previous item
            </button>
          )}
          <div className="item-meta">
            <span>{item.type}</span>
            <span>{item.source ?? "Source unavailable"}</span>
            <span>Saved {item.saved}</span>
            {item.edited && <span>Edited by you</span>}
          </div>
          {item.incomplete && (
            <div className="notice">
              <AlertCircle size={18} />
              <p>{item.incomplete}</p>
            </div>
          )}
          {item.intent && (
            <div className="saved-reason">
              <span>Your reason for saving</span>
              <p>{item.intent}</p>
            </div>
          )}
          <p className="item-lead">{item.lead}</p>
          <div className="knowledge">
            {item.sections.map((section, i) => (
              <section key={i}>
                <h3>{section.title}</h3>
                {section.paragraphs?.map((text, j) => (
                  <p key={j}>{text}</p>
                ))}
                {section.code && (
                  <div className="command">
                    <div className="command-tools">
                      <span>Command</span>
                      <button
                        className="quiet-button"
                        onClick={() => void copy(section.code!)}
                      >
                        <Copy size={15} />
                        Copy command
                      </button>
                    </div>
                    <pre tabIndex={0} aria-label="Command text">
                      <code>{section.code}</code>
                    </pre>
                  </div>
                )}
                {section.bullets && (
                  <ul>
                    {section.bullets.map((text, j) => (
                      <li key={j}>{text}</li>
                    ))}
                  </ul>
                )}
              </section>
            ))}
          </div>
          {copyError && (
            <p className="copy-error" role="status">
              Copy was blocked by your browser. Select the command or note text
              and copy it directly.
            </p>
          )}
          <section className="evidence-section">
            <h3>Source & evidence</h3>
            {item.citations.length ? (
              item.citations.map((citation, i) => (
                <details key={i}>
                  <summary>{citation.locator}</summary>
                  <blockquote>{citation.text}</blockquote>
                </details>
              ))
            ) : (
              <p className="muted">
                {item.edited
                  ? "This is a personal edited note; no extracted source passages are attached."
                  : "No source passages are attached to this sample note."}
              </p>
            )}
            {item.url && (
              <a
                className="source-link"
                href={item.url}
                target="_blank"
                rel="noopener noreferrer"
              >
                Open original source <ExternalLink size={14} />
              </a>
            )}
          </section>
          {!!item.related?.length && (
            <section className="related-section">
              <h3>Keep following this thread</h3>
              {item.related
                .map((id) => items.find((i) => i.id === id))
                .filter((n): n is Item => !!n)
                .map((n) => (
                  <button
                    className="related-link"
                    key={n.id}
                    onClick={() => related(n.id, body.current?.scrollTop ?? 0)}
                  >
                    <BookOpen size={16} />
                    <span>{n.title}</span>
                    <span className="muted">{n.type}</span>
                  </button>
                ))}
            </section>
          )}
          <details className="metadata-details">
            <summary>About this saved item</summary>
            <dl>
              <dt>Shelf</dt>
              <dd>{item.shelf}</dd>
              <dt>Topics</dt>
              <dd>{item.topics.join(", ")}</dd>
              <dt>Content</dt>
              <dd>
                Illustrative prototype knowledge
                {item.edited ? " · edited personal note" : ""}
              </dd>
            </dl>
          </details>
        </div>
      </div>
      <footer className="modal-footer">
        <span className="muted" role="status">
          {copyStatus || "Complete saved knowledge"}
        </span>
        <button
          className="quiet-button"
          onClick={() =>
            void copy(
              `# ${item.title}\n\n${item.sections.map((s) => `## ${s.title}\n${s.paragraphs?.join("\n\n") ?? ""}\n${s.code ?? ""}\n${s.bullets?.join("\n") ?? ""}`).join("\n\n")}`,
            )
          }
        >
          <Copy size={16} />
          Copy note
        </button>
      </footer>
    </>
  );
}
