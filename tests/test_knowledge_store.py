import json

import pytest

from infoparser.domain.models import Candidate, SegmentIn
from infoparser.store import knowledge as K
from infoparser.store.db import connect, migrate


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "t.db")
    migrate(c)
    return c


def cand(title, **kw):
    base = dict(kind="insight", title=title, body=f"body of {title}", data={}, provenance="inferred",
                evidence=None, segment_idx=0, confidence=0.5, entities=[], topics=[])
    return Candidate(**{**base, **kw})


def setup(conn):
    sid = K.save_source(conn, url="https://a.b/c", title="T", author=None, platform="web",
                        content_type="article", blob_sha256="x", text_sha256="y", extractor="text")
    segs = K.save_segments(conn, sid, [SegmentIn(0, "hello world", "char=0-11")])
    return sid, segs


def fts_titles(conn):
    return {r[0] for r in conn.execute(
        "SELECT i.title FROM items_fts f JOIN knowledge_items i ON i.rowid=f.rowid WHERE items_fts MATCH 'body'")}


def test_save_items_and_fts(conn):
    sid, segs = setup(conn)
    [iid] = K.save_items(conn, sid, [cand("one")], "m:x", segs)
    it = K.get_item(conn, iid)
    assert it["title"] == "one" and it["segment_refs"] == segs and it["extracted_by"] == "m:x"
    assert fts_titles(conn) == {"one"}
    K.delete_item(conn, iid)
    assert fts_titles(conn) == set() and K.get_item(conn, iid)["deleted_at"]


def test_save_items_reprocess_preserves_user_edited(conn):
    sid, segs = setup(conn)
    a, b = K.save_items(conn, sid, [cand("keep"), cand("drop")], "m:x", segs)
    K.update_item(conn, a, title="keep edited")
    new = K.save_items(conn, sid, [cand("fresh")], "m:y", segs)
    assert K.get_item(conn, a)["deleted_at"] is None and K.get_item(conn, a)["title"] == "keep edited"
    assert K.get_item(conn, b)["deleted_at"] is not None
    assert conn.execute("SELECT count(*) FROM knowledge_versions WHERE item_id=?", (b,)).fetchone()[0] == 1
    live = [r[0] for r in conn.execute("SELECT title FROM knowledge_items WHERE deleted_at IS NULL ORDER BY title")]
    assert live == ["fresh", "keep edited"] and len(new) == 1
    assert fts_titles(conn) == {"keep edited", "fresh"}


def test_update_item_writes_version(conn):
    sid, segs = setup(conn)
    [iid] = K.save_items(conn, sid, [cand("old")], "m:x", segs)
    K.update_item(conn, iid, title="new", data={"k": 1})
    it = K.get_item(conn, iid)
    assert it["version"] == 2 and it["user_edited"] == 1 and it["title"] == "new" and it["data"] == {"k": 1}
    v = conn.execute("SELECT version, title FROM knowledge_versions WHERE item_id=?", (iid,)).fetchone()
    assert (v[0], v[1]) == (1, "old")
    with pytest.raises(KeyError):
        K.update_item(conn, "nope", title="x")
    with pytest.raises(ValueError):
        K.update_item(conn, iid, bogus=1)


def _src(conn):
    return K.save_source(conn, url=None, title="T", author=None, platform="web", content_type="text",
                         blob_sha256="x", text_sha256="y", extractor="text")


@pytest.mark.parametrize("new_texts", [["a", "b"], ["changed", "second"]])
def test_reprocess_remaps_preserved_item_segment_refs(conn, new_texts):
    sid = _src(conn)
    segs = K.save_segments(conn, sid, [SegmentIn(0, "a", "l0"), SegmentIn(1, "b", "l1")])
    [iid] = K.save_items(conn, sid, [cand("mine", segment_idx=1)], "m", segs)
    K.update_item(conn, iid, title="mine!")
    segs2 = K.save_segments(conn, sid, [SegmentIn(i, t, f"l{i}") for i, t in enumerate(new_texts)])
    K.save_items(conn, sid, [cand("new", segment_idx=0)], "m", segs2)
    [ref] = K.get_item(conn, iid)["segment_refs"]
    assert tuple(conn.execute("SELECT idx, text FROM segments WHERE id=?", (ref,)).fetchone()) == (1, new_texts[1])
    assert conn.execute("SELECT count(*) FROM segments WHERE source_id=?", (sid,)).fetchone()[0] == 2


def test_reprocess_dropping_a_segment_drops_dangling_ref(conn):
    sid = _src(conn)
    segs = K.save_segments(conn, sid, [SegmentIn(0, "a", "l0"), SegmentIn(1, "b", "l1")])
    [iid] = K.save_items(conn, sid, [cand("mine", segment_idx=1)], "m", segs)
    K.update_item(conn, iid, title="mine!")
    K.save_segments(conn, sid, [SegmentIn(0, "a", "l0")])
    assert K.get_item(conn, iid)["segment_refs"] == []


def test_segment_refs_use_idx_not_list_position(conn):
    sid = _src(conn)
    segs = K.save_segments(conn, sid, [SegmentIn(5, "five", "l"), SegmentIn(7, "seven", "l")])
    [iid] = K.save_items(conn, sid, [cand("x", segment_idx=7)], "m", segs)
    [ref] = K.get_item(conn, iid)["segment_refs"]
    assert conn.execute("SELECT text FROM segments WHERE id=?", (ref,)).fetchone()[0] == "seven"


def test_update_item_data_merge_preserves_evidence_entities_topics(conn):
    sid, segs = setup(conn)
    [iid] = K.save_items(conn, sid, [cand("x", evidence="ev", entities=["E"], topics=["T"])], "m", segs)
    K.update_item(conn, iid, data={"note": "n", "topics": ["T2"]})
    assert K.get_item(conn, iid)["data"] == {"evidence": "ev", "entities": ["E"], "topics": ["T2"], "note": "n"}


def test_edit_and_delete_on_deleted_item(conn):
    sid, segs = setup(conn)
    [iid] = K.save_items(conn, sid, [cand("gone")], "m", segs)
    K.delete_item(conn, iid)
    conn.execute("UPDATE knowledge_items SET deleted_at='2000-01-01T00:00:00Z' WHERE id=?", (iid,))
    K.delete_item(conn, iid)
    assert K.get_item(conn, iid)["deleted_at"] == "2000-01-01T00:00:00Z"
    K.update_item(conn, iid, title="body edited")
    assert fts_titles(conn) == set()
