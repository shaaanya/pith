"""Link candidates' topics/entities to their saved items. Names are normalized (casefold, trimmed, inner
whitespace collapsed) and stored in that normalized form, so "OpenAI" and " openai " are one row.
ponytail: no alias table; merge is by normalized name only. Entity type is '' (candidates carry plain names)."""
from infoparser.domain.text import normalize
from infoparser.ids import new_id
from infoparser.store.db import transaction


def _names(values) -> set:
    """Only strings (and {"name": str} dicts) from a real list/tuple/set are kept; the rest is skipped."""
    if not isinstance(values, (list, tuple, set)):
        return set()
    out = set()
    for v in values:
        if isinstance(v, dict):
            v = v.get("name")
        if isinstance(v, str) and (n := normalize(v)):
            out.add(n)
    return out


def apply(conn, item_ids: list[str], candidates) -> None:
    """item_ids[i] corresponds to candidates[i]. Idempotent."""
    with transaction(conn):
        for iid, c in zip(item_ids, candidates):
            for n in _names(c.topics):
                conn.execute("INSERT OR IGNORE INTO topics(id, name) VALUES (?,?)", (new_id(), n))
                tid = conn.execute("SELECT id FROM topics WHERE name=?", (n,)).fetchone()[0]
                conn.execute("INSERT OR IGNORE INTO item_topics(item_id, topic_id) VALUES (?,?)", (iid, tid))
            for n in _names(c.entities):
                conn.execute("INSERT OR IGNORE INTO entities(id, name, type) VALUES (?,?,'')", (new_id(), n))
                eid = conn.execute("SELECT id FROM entities WHERE name=? AND type=''", (n,)).fetchone()[0]
                conn.execute("INSERT OR IGNORE INTO item_entities(item_id, entity_id) VALUES (?,?)", (iid, eid))
