"""Link candidates' topics/entities to their saved items. Names are normalized (casefold, trimmed, inner
whitespace collapsed) and stored in that normalized form, so "OpenAI" and " openai " are one row.
ponytail: no alias table; merge is by normalized name only. Entity type is '' (candidates carry plain names)."""
import re

from infoparser.ids import new_id
from infoparser.store.db import transaction


def normalize(name) -> str:
    if isinstance(name, dict):
        name = name.get("name", "")
    return re.sub(r"\s+", " ", str(name)).strip().casefold()


def apply(conn, item_ids: list[str], candidates) -> None:
    """item_ids[i] corresponds to candidates[i]. Idempotent."""
    with transaction(conn):
        for iid, c in zip(item_ids, candidates):
            for n in {normalize(x) for x in c.topics} - {""}:
                conn.execute("INSERT OR IGNORE INTO topics(id, name) VALUES (?,?)", (new_id(), n))
                tid = conn.execute("SELECT id FROM topics WHERE name=?", (n,)).fetchone()[0]
                conn.execute("INSERT OR IGNORE INTO item_topics(item_id, topic_id) VALUES (?,?)", (iid, tid))
            for n in {normalize(x) for x in c.entities} - {""}:
                conn.execute("INSERT OR IGNORE INTO entities(id, name, type) VALUES (?,?,'')", (new_id(), n))
                eid = conn.execute("SELECT id FROM entities WHERE name=? AND type=''", (n,)).fetchone()[0]
                conn.execute("INSERT OR IGNORE INTO item_entities(item_id, entity_id) VALUES (?,?)", (iid, eid))
