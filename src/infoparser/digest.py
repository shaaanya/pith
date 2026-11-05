"""Digest: what is new, what needs attention, a few older items to revisit, possible duplicates.
Delivery is file + stdout only (<home>/digests/YYYY-MM-DD.md). At most one per interval; `--dry-run` writes nothing.
Sections: new items since the last digest (grouped by topic, capped), inbox items failed/needs_clarification,
resurfaced older items (seeded RNG, at most RESURFACE_MAX), duplicate relations touching a new item
(relations carry no timestamp, so "found" means "involves an item created since the cutoff")."""
from __future__ import annotations

import datetime as dt
import random
import re
from dataclasses import dataclass
from pathlib import Path

RESURFACE_MAX = 5
_FILE = re.compile(r"(\d{4}-\d{2}-\d{2})\.md$")


@dataclass
class DigestRun:
    text: str
    path: Path | None = None
    skipped: bool = False


def _iso(d: dt.datetime) -> str:
    return d.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _line(s) -> str:
    """One-line, markdown-inert text: whitespace collapsed, structural characters neutralised."""
    t = " ".join(str(s or "").split())[:200] or "(untitled)"
    return re.sub(r"([\\`*_\[\]<>#|])", r"\\\1", t)


def _item(r) -> dict:
    return {"id": r["id"], "title": r["title"], "kind": r["kind"], "provenance": r["provenance"],
            "created_at": r["created_at"]}


def data(s, *, since_days: float = 7, since: str | None = None, max_items: int | None = None,
         seed=None, now: dt.datetime | None = None) -> dict:
    now = now or dt.datetime.now(dt.UTC)
    cap = max_items or s.cfg.digest_max_items
    cutoff = since or _iso(now - dt.timedelta(days=since_days))
    c = s.conn
    new = c.execute("SELECT id,title,kind,provenance,created_at FROM knowledge_items"
                    " WHERE deleted_at IS NULL AND created_at>=? ORDER BY created_at DESC, id", (cutoff,)).fetchall()
    topics = {}
    for r in new[:cap]:
        names = [x[0] for x in c.execute("SELECT t.name FROM item_topics i JOIN topics t ON t.id=i.topic_id"
                                         " WHERE i.item_id=? ORDER BY t.name", (r["id"],))] or [None]
        for n in names:
            topics.setdefault(n, []).append(_item(r))
    attention = [{"id": r["id"], "status": r["status"], "error": r["error"],
                  "what": r["canonical_url"] or r["original_filename"] or (r["payload_text"] or "")[:80]}
                 for r in c.execute("SELECT * FROM inbox_items WHERE status IN ('failed','needs_clarification')"
                                    " ORDER BY id")][:cap]
    old = [_item(r) for r in c.execute("SELECT id,title,kind,provenance,created_at FROM knowledge_items"
                                       " WHERE deleted_at IS NULL AND created_at<? ORDER BY id", (cutoff,))]
    rng = random.Random(str(seed if seed is not None else now.date()))
    resurfaced = sorted(rng.sample(old, min(RESURFACE_MAX, cap, len(old))), key=lambda i: i["id"])
    dups = [{"score": r["score"], "a": {"id": r["aid"], "title": r["atitle"]}, "b": {"id": r["bid"], "title": r["btitle"]}}
            for r in c.execute(
                "SELECT r.score, a.id aid, a.title atitle, b.id bid, b.title btitle FROM relations r"
                " JOIN knowledge_items a ON a.id=r.item_a AND a.deleted_at IS NULL"
                " JOIN knowledge_items b ON b.id=r.item_b AND b.deleted_at IS NULL"
                " WHERE r.type='duplicate' AND (a.created_at>=? OR b.created_at>=?) ORDER BY r.score DESC, a.id LIMIT ?",
                (cutoff, cutoff, cap))]
    total_items = c.execute("SELECT count(*) FROM knowledge_items WHERE deleted_at IS NULL").fetchone()[0]
    by_topic = {k or "(no topic)": v for k, v in sorted(topics.items(), key=lambda kv: (kv[0] is None, kv[0] or ""))}
    return {"since": cutoff, "generated_at": _iso(now), "library_items": total_items,
            "new": {"total": len(new), "items": [_item(r) for r in new[:cap]], "by_topic": by_topic},
            "attention": attention, "resurfaced": resurfaced, "duplicates": dups}


def render(d: dict) -> str:
    out = [f"# Digest {d['generated_at'][:10]}", ""]
    if d["library_items"] == 0 and not d["attention"]:
        return "\n".join(out + ["Your library is empty so far. Submit a URL, a file or a note "
                                "(`infoparser submit ...`, or drop files into your inbox folder) and the next digest "
                                "will have something to say.", ""])
    out += [f"Since {d['since']}.", "", "## New"]
    if d["new"]["total"] == 0:
        out.append("Nothing new in this period.")
    for topic, items in d["new"]["by_topic"].items():
        out += ["", f"### {_line(topic)}"]
        out += [f"- {_line(i['title'])} ({i['kind']}, {i['provenance']}) `{i['id']}`" for i in items]
    if d["new"]["total"] > len(d["new"]["items"]):
        out += ["", f"...and {d['new']['total'] - len(d['new']['items'])} more."]
    out += ["", "## Needs attention"]
    out += [f"- {a['status']}: {_line(a['what'])} `{a['id']}`" + (f" - {_line(a['error'])}" if a["error"] else "")
            for a in d["attention"]] or ["Nothing is stuck."]
    out += ["", "## Worth revisiting"]
    out += [f"- {_line(i['title'])} ({i['created_at'][:10]}) `{i['id']}`"
            for i in d["resurfaced"]] or ["Nothing older to resurface yet."]
    out += ["", "## Possible duplicates"]
    out += [f"- {_line(x['a']['title'])} / {_line(x['b']['title'])}"
            + (f" ({x['score']:.2f})" if x["score"] is not None else "") for x in d["duplicates"]] or ["None found."]
    return "\n".join(out + [""])


def build(s, since_days: float = 7, **kw) -> str:
    return render(data(s, since_days=since_days, **kw))


def _last(dirp: Path) -> dt.date | None:
    names = dirp.glob("*.md") if dirp.is_dir() else []
    return max((dt.date.fromisoformat(m[1]) for p in names if (m := _FILE.search(p.name))), default=None)


def run(s, *, since: str | None = None, dry_run: bool = False, today: dt.date | None = None,
        now: dt.datetime | None = None, seed=None) -> DigestRun:
    """since: ISO date (YYYY-MM-DD) or a number of days. Without it: since the last digest, else one interval back."""
    now = now or dt.datetime.now(dt.UTC)
    today = today or now.date()
    now = now.replace(year=today.year, month=today.month, day=today.day)
    dirp = Path(s.cfg.home) / "digests"
    interval = s.cfg.digest_interval_days
    last = _last(dirp)
    if last and not dry_run and since is None and (today - last).days < interval:
        nxt = last + dt.timedelta(days=interval)
        return DigestRun(f"A digest was already written for {last} (interval {interval} days); the next is due {nxt}. "
                         f"See {dirp / f'{last}.md'}.", dirp / f"{last}.md", skipped=True)
    if since is not None:
        cutoff = (_iso(dt.datetime.fromisoformat(since).replace(tzinfo=dt.UTC)) if "-" in since
                  else _iso(now - dt.timedelta(days=float(since))))
    elif last:
        cutoff = _iso(dt.datetime.combine(last, dt.time(), dt.UTC))
    else:
        cutoff = _iso(now - dt.timedelta(days=interval))
    text = render(data(s, since=cutoff, now=now, seed=seed or str(today)))
    if dry_run:
        return DigestRun(text)
    dirp.mkdir(parents=True, exist_ok=True)
    path = dirp / f"{today}.md"
    path.write_text(text, encoding="utf-8")
    return DigestRun(text, path)
