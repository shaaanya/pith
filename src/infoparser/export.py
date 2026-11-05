"""Markdown vault export: one file per live knowledge item at <vault>/<yyyy>/<slug>-<id>.md.
Derived and regenerable, never the source of truth; read-only on the database.

Frontmatter values are JSON scalars/arrays (JSON is valid YAML, so any YAML reader parses them and a hostile
title can never inject keys or break out of the block). Filenames are slugs + the 26-char id, so a title can
never traverse out of the vault. Re-export rewrites only files whose content changed; files for deleted or
renamed items are removed unless keep=True; only files matching *-<26-char id>.md are ever deleted."""
import json
import re
import unicodedata
from pathlib import Path

_ID_FILE = re.compile(r"-([0-9A-Z]{26})\.md$")
_YEAR = re.compile(r"\d{4}")
SLUG_MAX = 60


def slugify(title) -> str:
    t = unicodedata.normalize("NFKD", title or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")[:SLUG_MAX].strip("-") or "item"


def _fm(**kv) -> str:
    return "---\n" + "".join(f"{k}: {json.dumps(v, ensure_ascii=True)}\n" for k, v in kv.items()) + "---\n"


def _one_line(s) -> str:
    return " ".join(str(s or "").split())


def _render(c, r) -> tuple[str, str]:
    iid = r["id"]
    topics = [x[0] for x in c.execute("SELECT t.name FROM item_topics i JOIN topics t ON t.id=i.topic_id"
                                      " WHERE i.item_id=? ORDER BY t.name", (iid,))]
    ents = [x[0] for x in c.execute("SELECT e.name FROM item_entities i JOIN entities e ON e.id=i.entity_id"
                                    " WHERE i.item_id=? ORDER BY e.name", (iid,))]
    refs = json.loads(r["segment_refs"] or "[]")
    locs = [g[0] for sid in refs for g in c.execute("SELECT locator FROM segments WHERE id=?", (sid,)) if g[0]]
    src = c.execute("SELECT url, title FROM sources WHERE id=?", (r["source_id"],)).fetchone() if r["source_id"] else None
    ev = json.loads(r["data_json"] or "{}").get("evidence")
    head = _fm(id=iid, kind=r["kind"], title=r["title"] or "", provenance=r["provenance"],
               source_url=src["url"] if src else None, source_title=src["title"] if src else None,
               created=r["created_at"], updated=r["updated_at"], topics=topics, entities=ents, locators=locs)
    body = f"\n# {_one_line(r['title']) or 'Untitled'}\n\n{r['body'] or ''}\n"
    if ev or locs:
        body += "\n## Source\n"
        if ev:
            body += "\n" + "\n".join("> " + ln for ln in str(ev).splitlines()) + "\n"
        if locs:
            body += "\nLocators: " + ", ".join(locs) + "\n"
    return head + body, f"{slugify(r['title'])}-{iid}.md"


def export_vault(services, keep: bool = False) -> int:
    """-> number of live items represented in the vault."""
    c, root = services.conn, Path(services.cfg.vault_dir)
    want: dict[str, Path] = {}
    for r in c.execute("SELECT * FROM knowledge_items WHERE deleted_at IS NULL ORDER BY id").fetchall():
        text, name = _render(c, r)
        year = r["created_at"][:4] if _YEAR.fullmatch(r["created_at"][:4]) else "0000"
        path = root / year / name
        want[r["id"]] = path
        if not path.is_file() or path.read_text(encoding="utf-8") != text:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
    if not keep and root.is_dir():
        for p in root.glob("*/*.md"):
            m = _ID_FILE.search(p.name)
            if m and want.get(m[1]) != p and p.is_file() and not p.is_symlink():
                p.unlink()
    return len(want)
