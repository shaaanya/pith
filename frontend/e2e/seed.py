"""Realistic fixtures for the redesign journeys, written with Pith's own store functions into the
throwaway e2e home (never ~/Pith). Test data only; no application code is touched.

    uv run python frontend/e2e/seed.py <home> [volume]
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pith.domain.models import Candidate, SegmentIn
from pith.ids import new_id
from urllib.parse import urlparse

from pith.pipeline import entities, place
from pith.store import entries, knowledge, shelves
from pith.store.db import connect

home, volume = Path(sys.argv[1]), int(sys.argv[2]) if len(sys.argv) > 2 else 0
conn = connect(home / "infoparser.db")
NOW = datetime.now(timezone.utc)


def ts(days: float) -> str:
    return (NOW - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def note(title, url, platform, ctype, days, topics, units, *, intent=None, body=None, entities_=()):
    """One source -> segments -> a `note` item with typed units, like the note-v1 pipeline stores."""
    src = knowledge.save_source(
        conn, url=url, title=title, author=None, platform=platform, content_type=ctype,
        blob_sha256=None, text_sha256=new_id(), extractor="seed",
    )
    text = " ".join(u[1] for u in units)
    sids = knowledge.save_segments(conn, src, [SegmentIn(0, text, "char=0-%d" % len(text))])
    md = body or "\n".join(f"- {u[1]}" for u in units)
    if intent:
        md = f"**Why saved:** {intent}\n\n{md}"
    data = {
        "units": [{"type": t, "text": x, "support": 0.9, "focus": False, "segment_idx": 0} for t, x in units],
        "intent": {"state": "explicit" if intent else "unknown", "text": intent},
        "limits": [], "gaps": [], "dropped": {}, "repairs": [], "stats": {}, "version": "note-v1",
    }
    cand = Candidate(kind="note", title=title, body=md, data=data, provenance="stated",
                     segment_idx=0, confidence=0.82, topics=list(topics), entities=list(entities_))
    ids = knowledge.save_items(conn, src, [cand], "seed", sids)
    entities.apply(conn, ids, [cand])
    conn.execute("UPDATE knowledge_items SET created_at=?, updated_at=? WHERE id=?", (ts(days), ts(days), ids[0]))
    # what the pipeline's place and entries stages do after save (the seed bypasses the pipeline)
    shelf, by, why = place.rules(intent, urlparse(url).netloc if url else None, bool(topics))
    shelves.set_placement(conn, ids[0], shelf, by, why)
    entries.sync(conn, src, ids[0], [x for t, x in units if t == "resource"])
    return ids[0]


note(
    "Five slow-burn thrillers worth a weekend", "https://www.instagram.com/reel/C1xYz9/", "instagram", "video", 5,
    ["film", "recommendations"],
    [("resource", "Prisoners (2013): a missing-child thriller, directed by Denis Villeneuve"),
     ("resource", "Zodiac (2007): David Fincher's procedural about the Zodiac killer"),
     ("resource", "Memories of Murder (2003): Bong Joon-ho's serial-killer drama"),
     ("resource", "Wind River (2017): a tracker and an FBI agent on a reservation"),
     ("resource", "The Vanishing (1988): the original Dutch version, not the remake"),
     ("fact", "The creator says all five are streaming for free in some regions")],
    intent="watch these on the weekend", entities_=["Prisoners", "Zodiac", "Memories of Murder"],
)
note(
    "uv: a fast Python package and project manager", "https://github.com/astral-sh/uv", "web", "web", 12,
    ["python", "tooling"],
    [("fact", "uv replaces pip, pip-tools, virtualenv and pyenv with one Rust binary"),
     ("step", "Install with `curl -LsSf https://astral.sh/uv/install.sh | sh`"),
     ("step", "Run `uv init` to create a project, then `uv add requests`"),
     ("claim", "The README claims 10 to 100 times faster installs than pip")],
    intent="try this for my python projects",
)
note(
    "ripgrep: recursive line-oriented search", "https://github.com/BurntSushi/ripgrep", "web", "web", 34,
    ["tooling", "cli"],
    [("fact", "ripgrep respects .gitignore by default and skips binary files"),
     ("resource", "Config file via the RIPGREP_CONFIG_PATH environment variable")],
)
note(
    "Postgres logical replication, step by step", "https://example.com/blog/pg-logical", "web", "web", 3,
    ["postgres", "databases", "replication"],
    [("step", "Set `wal_level = logical` on the primary and restart it"),
     ("step", "Create a publication: `CREATE PUBLICATION app_pub FOR ALL TABLES;`"),
     ("step", "On the replica run `CREATE SUBSCRIPTION app_sub CONNECTION 'host=10.0.0.5 dbname=app' PUBLICATION app_pub;`"),
     ("step", "Check lag with `SELECT * FROM pg_stat_subscription;`"),
     ("fact", "Initial table copy runs in the background and can take hours on large tables"),
     ("warning", "Sequences are not replicated: advance them manually before cutover"),
     ("warning", "DDL changes are not replicated: apply schema changes on both sides"),
     ("resource", "pgbadger reads Postgres logs and produces an HTML report")],
    intent="need this for the migration next month",
    body=(
        "## Steps\n\n1. Set `wal_level = logical` on the primary and restart it.\n"
        "2. Create a publication:\n\n```sql\nCREATE PUBLICATION app_pub FOR ALL TABLES;\n```\n\n"
        "3. On the replica:\n\n```sql\nCREATE SUBSCRIPTION app_sub\n  CONNECTION 'host=10.0.0.5 dbname=app'\n  PUBLICATION app_pub;\n```\n\n"
        "4. Check lag with `SELECT * FROM pg_stat_subscription;`\n\n## Facts\n\n- Initial table copy runs in the background.\n\n"
        "## Watch out\n\n- Sequences are not replicated.\n- DDL changes are not replicated."
    ),
)
note(
    "Hounds of Love, Kate Bush", "https://open.spotify.com/album/0abc", "web", "web", 20, ["music"],
    [("fact", "1985 album; side two is a seven-song suite called The Ninth Wave")],
)
note(
    "Perfect Days (2023)", "https://letterboxd.com/film/perfect-days/", "web", "web", 9, ["film"],
    [("fact", "Wim Wenders film about a Tokyo toilet cleaner; 124 minutes")],
)
note(
    "Sourdough starter feeding schedule", None, "unknown", "note", 8, ["baking", "food"],
    [("step", "Keep 50g starter, add 50g flour and 50g water at 24C"), ("fact", "It doubles in 4 to 6 hours")],
    intent="weekend baking",
)
note(
    "Kubernetes debugging cheatsheet", None, "unknown", "note", 2, ["kubernetes", "postgres"],
    [("step", "kubectl describe pod, then kubectl logs --previous"),
     ("fact", "Exit code 137 usually means OOMKilled; raise the memory limit")],
)
note("A random thought about naming things", None, "unknown", "note", 1, [], [("claim", "Names should say what, not how")])

# A failed Instagram item: login-walled, the classic reel failure.
conn.execute(
    "INSERT INTO inbox_items(id,adapter,platform,submitted_at,content_type,payload_text,canonical_url,status,error,attempts,updated_at)"
    " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
    (new_id(), "telegram", "instagram", ts(0.2), "url", "https://www.instagram.com/reel/C9failed/",
     "https://www.instagram.com/reel/C9failed/", "failed", "HTTP 403: login required", 2, ts(0.2)),
)

for i in range(volume):
    note(
        f"Bulk note {i}: {['kubernetes', 'rust', 'sleep', 'tax', 'cycling', 'jazz', 'espresso'][i % 7]} detail {i}",
        None, "unknown", "note", 1 + (i % 400) / 2, [f"topic{i % 40}"], [("fact", f"Fact number {i} about topic{i % 40}")],
    )
print("seeded", volume, "bulk notes")
