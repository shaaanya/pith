export type Dataset = "empty" | "sparse" | "rich";
export type Workspace = "overview" | "focus";
export type Shelf = "Read" | "Try" | "Watch" | "Listen" | "Visit" | "Reference";
export type Section = {
  title: string;
  paragraphs?: string[];
  bullets?: string[];
  code?: string;
};
export type Item = {
  id: string;
  title: string;
  type: string;
  shelf: Shelf;
  source?: string;
  url?: string;
  saved: string;
  lead: string;
  intent?: string;
  sections: Section[];
  citations: { locator: string; text: string }[];
  related?: string[];
  topics: string[];
  edited?: boolean;
  incomplete?: string;
};
export type Group = {
  id: string;
  title: string;
  description: string;
  icon: string;
  itemIds: string[];
};
export const shelves: Shelf[] = [
  "Watch",
  "Read",
  "Listen",
  "Try",
  "Visit",
  "Reference",
];

const notes: Item[] = [
  {
    id: "rga",
    title: "ripgrep-all: search inside documents",
    type: "Tool",
    shelf: "Try",
    source: "GitHub · phiresky/ripgrep-all",
    url: "https://github.com/phiresky/ripgrep-all",
    saved: "12 Nov",
    lead: "Use one search across PDFs, e-books, SQLite databases, and archives, without opening every file.",
    intent: "Find the notes I keep remembering but cannot locate.",
    sections: [
      {
        title: "What it does",
        paragraphs: [
          "ripgrep-all (rga) wraps ripgrep with adapters that extract searchable text from different file formats. You search the content rather than just filenames.",
          "Keep the original documents: the extracted text is a search aid, not a replacement for the source. Supported formats and adapter requirements depend on the installed version.",
        ],
      },
      {
        title: "A command to keep",
        code: 'rga --max-count 3 "POSIX lock" ~/Documents/references/',
        paragraphs: [
          "Search recursively for the phrase and limit matching lines per file. Quote paths containing spaces. This example is text to copy; the prototype never executes it.",
        ],
      },
      {
        title: "Before trying it",
        bullets: [
          "Install ripgrep-all and the adapters needed for your document formats.",
          "Try a small directory first; extraction of a large collection may take time.",
          "Open the original source when a search result needs more context.",
        ],
      },
      {
        title: "A useful distinction",
        paragraphs: [
          "Searching extracted text can bring a forgotten passage back into reach. It does not establish that the passage is accurate or current. Check the source and its date before relying on it.",
        ],
      },
    ],
    citations: [
      {
        locator: "README · overview",
        text: "ripgrep-all extends ripgrep with document adapters. This is an illustrative saved note; use the linked project documentation for current supported formats.",
      },
    ],
    related: ["sqlite", "zoxide"],
    topics: ["search", "tools", "documents"],
  },
  {
    id: "sqlite",
    title: "SQLite WAL and shared storage",
    type: "Article",
    shelf: "Reference",
    source: "SQLite documentation",
    url: "https://sqlite.org/wal.html",
    saved: "10 Nov",
    lead: "Write-ahead logging is a local coordination mechanism, not a shortcut to a multi-machine database.",
    sections: [
      {
        title: "The important constraint",
        paragraphs: [
          "WAL coordinates readers and a writer using shared memory. Processes accessing the database need to be on the same host. Do not place a WAL database on a network filesystem and assume it will behave like a server database.",
        ],
      },
      {
        title: "When to revisit this",
        bullets: [
          "A local application starts using several worker processes.",
          "A database file is being moved to a shared drive.",
          "Backups need to include committed changes still in the WAL.",
        ],
      },
      {
        title: "Keep the distinction clear",
        paragraphs: [
          "Multiple readers can coexist with a writer. Multiple simultaneous writers are still serialized. Choose the deployment model before changing database settings.",
        ],
      },
    ],
    citations: [
      {
        locator: "WAL · disadvantages",
        text: "All processes using a WAL database must be on the same host computer; WAL does not work over a network filesystem.",
      },
    ],
    related: ["rga", "indexes"],
    topics: ["databases", "systems"],
  },
  {
    id: "indexes",
    title: "Reading a query plan before adding an index",
    type: "PDF",
    shelf: "Read",
    source: "Saved workshop handout",
    saved: "9 Nov",
    lead: "Start with the query and its access pattern, then decide whether an index solves the actual problem.",
    intent: "Bring one clear example to the interview.",
    sections: [
      {
        title: "A small diagnostic loop",
        bullets: [
          "Write down the query and the rows it needs.",
          "Inspect the query plan with representative data.",
          "Check estimated and actual rows where the database supports it.",
          "Change one thing, measure again, and account for write overhead.",
        ],
      },
      {
        title: "Example to discuss",
        code: "EXPLAIN QUERY PLAN\nSELECT title FROM notes WHERE topic = 'systems';",
      },
      {
        title: "What this note does not cover",
        paragraphs: [
          "The handout compares simple filters. It does not establish an index strategy for every query, database engine, or production workload.",
        ],
      },
    ],
    citations: [
      {
        locator: "Page 4 · diagnostic loop",
        text: "An index is useful when its access pattern matches the query. Measure the workload before and after the change.",
      },
    ],
    related: ["sqlite"],
    topics: ["databases", "learning"],
  },
  {
    id: "zoxide",
    title: "zoxide: find a familiar directory again",
    type: "Tool",
    shelf: "Try",
    source: "GitHub · ajeetdsouza/zoxide",
    url: "https://github.com/ajeetdsouza/zoxide",
    saved: "8 Nov",
    lead: "Jump to directories using a short name from the paths you have visited.",
    sections: [
      {
        title: "The idea",
        paragraphs: [
          "zoxide learns the directories you use and offers a shorter way back. It can reduce repeated navigation through long folder trees.",
        ],
      },
      {
        title: "After installation and shell setup",
        code: "z projects\nzi",
        paragraphs: [
          "The first example jumps to a matching directory. Interactive selection depends on the optional tools described in the project documentation.",
        ],
      },
    ],
    citations: [],
    related: ["rga"],
    topics: ["tools", "terminal"],
  },
  {
    id: "flame",
    title: "What a flame graph can tell you",
    type: "Guide",
    shelf: "Try",
    source: "Brendan Gregg · flame graphs",
    url: "https://www.brendangregg.com/flamegraphs.html",
    saved: "7 Nov",
    lead: "A wide frame reflects sampled time on a stack, not necessarily a slow individual call.",
    sections: [
      {
        title: "Read the width, not the height",
        paragraphs: [
          "Width represents the share of sampled time. Height represents stack depth. A deep stack is not automatically a performance problem.",
        ],
      },
      {
        title: "Before changing code",
        bullets: [
          "Understand what was sampled and over what interval.",
          "Look for wide stacks relevant to the user-visible slowdown.",
          "Repeat measurements after a targeted change.",
        ],
      },
    ],
    citations: [
      {
        locator: "Flame graphs · interpretation",
        text: "Flame graphs visualize profiled stack traces. Their widths indicate relative frequency in the sampled profile.",
      },
    ],
    topics: ["systems", "profiling"],
  },
  {
    id: "harper",
    title: "Harper: a grammar checker that runs locally",
    type: "Tool",
    shelf: "Try",
    source: "GitHub · Automattic/harper",
    url: "https://github.com/Automattic/harper",
    saved: "6 Nov",
    lead: "A possible writing companion for catching small mistakes without leaving the editor.",
    sections: [
      {
        title: "Why keep it",
        paragraphs: [
          "A local grammar checker may help with routine mistakes while keeping editing close to the document. Check the available editor integrations and language support before choosing one.",
        ],
      },
    ],
    citations: [],
    topics: ["tools", "writing"],
  },
  {
    id: "mitm",
    title: "mitmproxy: understand an HTTP conversation",
    type: "Tool",
    shelf: "Try",
    source: "mitmproxy documentation",
    url: "https://docs.mitmproxy.org/stable/",
    saved: "5 Nov",
    lead: "Inspect requests and responses when diagnosing software you control.",
    sections: [
      {
        title: "What to use it for",
        paragraphs: [
          "An interactive proxy helps inspect a sequence of HTTP requests, understand unexpected responses, and reproduce a problem. Use it only with systems and traffic you are authorized to inspect.",
        ],
      },
      {
        title: "Keep context with the capture",
        bullets: [
          "Record the action that triggered the request.",
          "Remove credentials and private data before sharing traces.",
          "Consult the source documentation for certificate and client setup.",
        ],
      },
    ],
    citations: [],
    topics: ["tools", "networking"],
  },
  {
    id: "nushell",
    title: "Nushell: think in structured tables",
    type: "Tool",
    shelf: "Try",
    source: "Nushell book",
    url: "https://www.nushell.sh/book/",
    saved: "4 Nov",
    lead: "A shell experiment for working with structured data rather than parsing columns of text.",
    sections: [
      {
        title: "Something small to try",
        code: "ls | where type == file | sort-by size | reverse | first 5",
        paragraphs: [
          "Explore a directory as structured records. This sample note is a starting point, not a complete shell migration guide.",
        ],
      },
    ],
    citations: [],
    topics: ["tools", "terminal"],
  },
  {
    id: "films",
    title: "Five films for an unhurried weekend",
    type: "Reel · 5 films",
    shelf: "Watch",
    source: "Saved video note",
    saved: "3 Nov",
    lead: "A small shortlist of slow-burn stories, kept together with the source that mentioned them.",
    intent: "Pick one for a quiet evening, not all five.",
    sections: [
      {
        title: "The five recommendations",
        bullets: [
          "Prisoners (2013) — a missing-child thriller directed by Denis Villeneuve.",
          "Zodiac (2007) — David Fincher follows an investigation over many years.",
          "Memories of Murder (2003) — a procedural drama from Bong Joon-ho.",
          "Wind River (2017) — a mystery set in a remote winter landscape.",
          "The Vanishing (1988) — the original Dutch film.",
        ],
      },
      {
        title: "A note about availability",
        paragraphs: [
          "The saved source mentioned the films, not current streaming availability. Check a service you use before settling in.",
        ],
      },
    ],
    citations: [
      {
        locator: "Video note · extracted titles",
        text: "The five titles are illustrative extracted entries from a sample reel. Their source is kept as a single note rather than five fabricated documents.",
      },
    ],
    related: ["perfect", "walk"],
    topics: ["film", "weekend"],
  },
  {
    id: "perfect",
    title: "Perfect Days: finding a rhythm in ordinary life",
    type: "Film",
    shelf: "Watch",
    source: "Official film page",
    url: "https://www.perfectdays-movie.com/",
    saved: "2 Nov",
    lead: "A quiet story built around work, music, books, and small changes in a daily rhythm.",
    sections: [
      {
        title: "Why it stayed with me",
        paragraphs: [
          "The film leaves room for observation. This sample personal note keeps the reason for saving it, rather than manufacturing a rating or an obligation to watch.",
        ],
      },
    ],
    citations: [],
    topics: ["film", "weekend"],
  },
  {
    id: "walk",
    title: "A walk without headphones",
    type: "Voice note",
    shelf: "Listen",
    source: "Personal voice memo",
    saved: "1 Nov",
    lead: "Leave enough room in a day to notice what is already there.",
    edited: true,
    sections: [
      {
        title: "My note",
        paragraphs: [
          "Try the river path on Sunday morning. No route target, no distance to finish. Bring a notebook if there is something worth keeping.",
          "I edited this after listening again: the useful part was not the walking advice, but the reminder that every quiet moment does not need to be filled.",
        ],
      },
    ],
    citations: [],
    topics: ["weekend", "reflection"],
  },
  {
    id: "crdt",
    title: "Local-first software and the shape of collaboration",
    type: "Essay",
    shelf: "Read",
    source: "Ink & Switch",
    url: "https://www.inkandswitch.com/local-first/",
    saved: "30 Oct",
    lead: "Ownership and offline access change the way we think about a shared document.",
    sections: [
      {
        title: "The central idea",
        paragraphs: [
          "Local-first software treats the local copy as primary and uses synchronization to support collaboration. It aims to combine user ownership with useful cooperation.",
          "This introduces real design questions: conflict handling, device loss, backups, and the user’s understanding of what has synchronized.",
        ],
      },
      {
        title: "Questions to keep",
        bullets: [
          "Does the document still work without a network connection?",
          "Can I export and keep my own copy?",
          "How are conflicting edits explained to the people who made them?",
        ],
      },
    ],
    citations: [
      {
        locator: "Essay · ideals",
        text: "Offline work, collaboration, longevity, privacy, and user control are discussed as goals of local-first software.",
      },
    ],
    related: ["sqlite"],
    topics: ["systems", "ownership"],
  },
  {
    id: "attention",
    title: "A thought about keeping things within reach",
    type: "Personal note",
    shelf: "Reference",
    source: "Personal notebook",
    saved: "28 Oct",
    lead: "Make returning easy without putting every saved thing in the foreground.",
    sections: [
      {
        title: "Keep the door, not the whole room",
        paragraphs: [
          "A useful index is a set of recognizable doors. I should be able to see where something belongs, open the right door, and find enough context to choose.",
          "Showing less is helpful only when the next step remains visible and dependable. Hidden is different from forgotten.",
        ],
      },
    ],
    citations: [],
    topics: ["design", "reflection"],
  },
  {
    id: "unreadable",
    title: "A saved talk that needs its transcript",
    type: "Incomplete video",
    shelf: "Read",
    source: "Sample capture",
    saved: "Yesterday",
    lead: "The source was saved, but the spoken content could not be extracted.",
    incomplete:
      "No transcript was available for this sample capture. The note cannot summarize what it has not read.",
    sections: [
      {
        title: "What is available",
        paragraphs: [
          "Only the saved title and your original context remain. No facts or recommendations were invented to fill the gap.",
        ],
      },
      {
        title: "A possible next step",
        paragraphs: [
          "In the production app, a readable transcript may help. This isolated prototype does not upload files or retry captures.",
        ],
      },
    ],
    citations: [],
    topics: ["learning"],
  },
];

export function makeDataset(dataset: Dataset): {
  items: Item[];
  groups: Group[];
} {
  if (dataset === "empty") return { items: [], groups: [] };
  const items =
    dataset === "sparse"
      ? notes.filter((n) =>
          ["rga", "films", "walk", "attention", "unreadable"].includes(n.id),
        )
      : [...notes];
  const groups: Group[] =
    dataset === "sparse"
      ? [
          {
            id: "in-reach",
            title: "Within reach",
            description: "A few things to return to",
            icon: "bookmark",
            itemIds: items.map((i) => i.id),
          },
        ]
      : [
          {
            id: "systems",
            title: "SQL & Systems Diagnostics",
            description: "A passage, a plan, a useful distinction",
            icon: "database",
            itemIds: ["sqlite", "indexes", "flame", "crdt"],
          },
          {
            id: "tools",
            title: "Tools to Check Out",
            description: "Small tools for familiar problems",
            icon: "terminal",
            itemIds: ["rga", "zoxide", "flame", "harper", "mitm", "nushell"],
          },
          {
            id: "weekend",
            title: "Cultural Weekend",
            description: "Something to watch, hear, or wander through",
            icon: "book",
            itemIds: ["films", "perfect", "walk"],
          },
          {
            id: "exploring",
            title: "Currently Exploring",
            description: "Follow a thread without a deadline",
            icon: "compass",
            itemIds: ["crdt", "rga", "unreadable"],
          },
          {
            id: "interview",
            title: "SQL Interview Prep",
            description: "Ideas worth being able to explain",
            icon: "layers",
            itemIds: ["indexes", "sqlite"],
          },
          {
            id: "remember",
            title: "Things Worth Remembering",
            description: "A place for ideas that stay useful",
            icon: "bookmark",
            itemIds: ["attention", "walk", "crdt"],
          },
        ];
  if (dataset === "rich") {
    for (let n = 1; n <= 2986; n++)
      items.push({
        id: `archive-${n}`,
        title: `${["Observations on a reading practice", "Notes from a systems workshop", "An idea for a quieter workspace", "A useful passage about maps"][n % 4]} · ${n}`,
        type: n % 2 ? "Article" : "Personal note",
        shelf: n % 2 ? "Read" : "Reference",
        source: "Sample archive",
        saved: "Earlier",
        lead: "An illustrative archive note for testing browsing, long collections, and returning to a context.",
        sections: [
          {
            title: "A passage to return to",
            paragraphs: [
              "The purpose of this sample is to exercise real navigation and reading with a large collection. It is a complete short fixture, not a claim extracted from a real source.",
            ],
          },
        ],
        citations: [],
        topics: ["archive"],
      });
    groups.push({
      id: "reading",
      title: "A Longer Reading Thread",
      description: "A larger collection, a little at a time",
      icon: "book",
      itemIds: items
        .filter((i) => i.id.startsWith("archive-"))
        .slice(0, 60)
        .map((i) => i.id),
    });
  }
  return { items, groups };
}
