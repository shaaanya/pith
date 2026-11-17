import { render, screen } from "@testing-library/react";
import { Markdown, parseBlocks } from "./markdown";
import { snippetParts, explainError, cleanTitle } from "./format";
import { safeHref } from "./utils";

describe("markdown", () => {
  it("parses headings, lists and fenced code", () => {
    const b = parseBlocks("# T\n\n1. one\n2. two\n\n- a\n- b\n\n```\nx = 1\n```\n");
    expect(b.map((x) => x.t)).toEqual(["h", "ol", "ul", "code"]);
  });
  it("renders steps as an ordered list and never creates unsafe links", () => {
    render(<Markdown source={"1. open [x](javascript:alert(1))\n2. see https://example.com/a."} />);
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveAttribute("href", "https://example.com/a");
    expect(links[0]).toHaveAttribute("rel", expect.stringContaining("noopener"));
  });
  it("does not interpret HTML", () => {
    const { container } = render(<Markdown source={"<img src=x onerror=alert(1)> **bold**"} />);
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("strong")).toHaveTextContent("bold");
  });
});

describe("format helpers", () => {
  it("splits search snippets into highlight runs", () => {
    expect(snippetParts("...The tool [pgbadger] is handy")).toEqual([
      { text: "...The tool ", hit: false },
      { text: "pgbadger", hit: true },
      { text: " is handy", hit: false },
    ]);
  });
  it("turns raw errors into plain language", () => {
    expect(explainError("failed", "URLError: <urlopen error [Errno 61] Connection refused>").title).toBe("Could not reach it");
    expect(explainError("needs_clarification", "no captions").canPaste).toBe(true);
  });
  it("keeps only the file name of path-like titles and only http(s) hrefs", () => {
    expect(cleanTitle("/tmp/a/b/clip.mp4")).toBe("clip.mp4");
    expect(safeHref("javascript:alert(1)")).toBeUndefined();
    expect(safeHref("https://a.b/c")).toBe("https://a.b/c");
  });
});
