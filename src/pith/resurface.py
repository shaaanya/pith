"""Explainable resurfacing: an older note is offered only when a stated reason holds, never at random.

Reasons, strongest first:
  intent  you wrote a reason when saving, the note is on an action shelf, and it is not marked done
  topic   it shares a specific topic with at least two notes you saved this week
  shelf   it has waited two weeks or more on an action shelf you (or your reason or a known site) chose
Only notes at least 14 days old are offered (newer open items are already in front of you). Snoozed and
hidden notes are skipped. Returns nothing when no reason holds. Port of frontend/src/lib/resurface.ts."""
import datetime as dt
import json
import re
from collections import defaultdict

DAY = 86_400
MAX = 3


def _ts(iso: str) -> float:
    return dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


def _ago(iso: str, now: float) -> str:
    d = max(1, round((now - _ts(iso)) / DAY))
    return (f"{round(d / 30)} months ago" if d >= 60 else
            f"{round(d / 7)} weeks ago" if d >= 14 else f"{d} days ago")


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def resurface(conn, now: dt.datetime | None = None, limit: int = MAX) -> list[dict]:
    """[{id, title, shelf, kind, why, score}], best first, at most `limit`."""
    now_s = (now or dt.datetime.now(dt.UTC)).timestamp()
    shelves = {r["id"]: r for r in conn.execute("SELECT id, name, todo FROM shelves")}
    rows = conn.execute(
        "SELECT k.id, k.title, k.created_at, k.data_json, k.body, k.shelf_id, k.placement_by,"
        " ns.done_at, ns.snooze_until, ns.hidden FROM knowledge_items k"
        " LEFT JOIN note_state ns ON ns.owner=COALESCE(k.source_id, k.id)"
        " WHERE k.deleted_at IS NULL AND (k.kind='note' OR (k.kind='summary' AND NOT EXISTS"
        " (SELECT 1 FROM knowledge_items n WHERE n.source_id=k.source_id AND n.kind='note'"
        " AND n.deleted_at IS NULL)))").fetchall()
    topics = defaultdict(list)
    for r in conn.execute("SELECT i.item_id, t.name FROM item_topics i JOIN topics t"
                          " ON t.id=i.topic_id"):
        topics[r["item_id"]].append(r["name"])

    total = len(rows) or 1
    count, recent_by = defaultdict(int), defaultdict(list)
    for r in rows:
        for t in topics[r["id"]]:
            count[t] += 1
    for r in rows:
        if now_s - _ts(r["created_at"]) < 7 * DAY:
            for t in topics[r["id"]]:
                if count[t] / total <= 0.25:  # on most notes says nothing
                    recent_by[t].append(r["id"])

    out = []
    for r in rows:
        if r["hidden"] or (r["snooze_until"] and _ts(r["snooze_until"]) > now_s):
            continue
        age = now_s - _ts(r["created_at"])
        if age < 14 * DAY:
            continue
        shelf = shelves.get(r["shelf_id"] or "other")
        by = r["placement_by"]
        on_todo = bool(shelf and shelf["todo"]) and not r["done_at"]
        intent = (json.loads(r["data_json"] or "{}").get("intent") or {}).get("text")
        if not intent and (m := re.search(r"\*\*Why saved:\*\*\s*(.+)", r["body"] or "")):
            intent = m[1].strip()
        base = {"id": r["id"], "title": r["title"], "created_at": r["created_at"],
                "shelf": r["shelf_id"] or "other"}
        if on_todo and intent and by:
            out.append({**base, "kind": "intent", "score": 100 + min(age / DAY, 90),
                        "why": f"You saved this {_ago(r['created_at'], now_s)} with the reason "
                               f"“{intent}” and haven't marked it done."})
            continue
        best = None
        for t in topics[r["id"]]:
            w = [x for x in recent_by[t] if x != r["id"]]
            if len(w) >= 2 and (best is None or len(w) > best[1]):
                best = (t, len(w))
        if best:
            out.append({**base, "kind": "topic", "score": 50 + best[1] * 5,
                        "why": f"Connects to “{best[0]}”, which "
                               f"{_plural(best[1], 'note')} you saved this week also cover."})
            continue
        if on_todo and by not in (None, "default"):
            out.append({**base, "kind": "shelf", "score": 20 + min(age / DAY, 60) / 10,
                        "why": f"Waiting on your {shelf['name']} shelf since "
                               f"{_ago(r['created_at'], now_s)}, not marked done."})
    return sorted(out, key=lambda x: (-x["score"], x["id"]))[:limit]
