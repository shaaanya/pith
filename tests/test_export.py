"""Markdown vault export: idempotence, hostile titles, deletes, retitles."""
import hashlib
import json
from pathlib import Path

from pith import export
from pith.pipeline import runner
from pith.store import knowledge

NOTES = ["Quokkas are small marsupials from Australia. They live on Rottnest Island.",
         "Sourdough needs a long fermentation and a hot oven for good crust."]


def load(svc, notes=None):
    """Submit and process each note; returns the inbox ids."""
    ids = []
    for t in notes or NOTES:
        iid = svc.inbox.submit(adapter="t", text=t).id
        runner.process(svc, iid)
        ids.append(iid)
    return ids


def parse(path: Path):
    """Front matter (JSON-valued lines) and body of an exported note."""
    head, body = path.read_text().split("\n---\n", 1)
    assert head.startswith("---\n")
    fm = {}
    for line in head[4:].splitlines():
        k, _, v = line.partition(": ")
        fm[k] = json.loads(v)  # every value is a JSON scalar/array: valid YAML, no YAML lib needed
    return fm, body


def files(svc):
    """Exported markdown files."""
    return sorted(svc.cfg.vault_dir.rglob("*.md"))


def test_export_idempotent_and_frontmatter_parses(svc):
    """Re-export leaves files untouched; front matter parses."""
    load(svc)
    n = export.export_vault(svc)
    assert n == len(files(svc)) and n >= 2
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in files(svc)}
    assert export.export_vault(svc) == n
    assert {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in files(svc)} == before  # untouched
    fm, _ = parse(files(svc)[0])
    assert {"id", "kind", "provenance", "source_url", "created", "topics", "entities",
            "locators"} <= set(fm)
    assert isinstance(fm["topics"], list) and len(fm["id"]) == 26
    assert fm["created"][:4] in files(svc)[0].parent.name
    assert any("Quokkas" in p.read_text() or "Sourdough" in p.read_text() for p in files(svc))


def test_hostile_titles_stay_inside_vault_and_roundtrip(svc):
    """Hostile titles cannot escape the vault and round-trip through front matter."""
    ids = load(svc, [f"note number {i} about distinct topic {i}" for i in range(5)])
    titles = ["../../etc/x", "CON", "a" * 600, "☃ snow: \"quoted\"\nnewline --- # [x]",
              "/abs/../../root"]
    for i, t in zip(ids, titles):
        item = svc.conn.execute(
            "SELECT id FROM knowledge_items WHERE source_id="
            "(SELECT source_id FROM inbox_items WHERE id=?) LIMIT 1", (i,)).fetchone()
        knowledge.update_item(svc.conn, item["id"], title=t)
    export.export_vault(svc)
    root = svc.cfg.vault_dir.resolve()
    got = set()
    for p in files(svc):
        assert root in p.resolve().parents and len(p.name) < 120
        assert p.parent.parent == svc.cfg.vault_dir
        fm, _ = parse(p)
        got.add(fm["title"])
    assert set(titles) <= got
    assert not (svc.cfg.home / "etc").exists() and not Path("/root/x").exists()


def test_deleted_items_removed_unless_keep_and_foreign_files_untouched(svc):
    """Deleted items disappear unless kept; foreign files are never touched."""
    load(svc)
    export.export_vault(svc)
    mine = svc.cfg.vault_dir / "notes.md"
    mine.write_text("mine")
    iid = svc.conn.execute("SELECT id FROM knowledge_items LIMIT 1").fetchone()["id"]
    knowledge.delete_item(svc.conn, iid)
    export.export_vault(svc, keep=True)
    assert any(iid in p.name for p in files(svc))
    export.export_vault(svc)
    assert not any(iid in p.name for p in files(svc)) and mine.read_text() == "mine"


def test_retitle_renames_file_no_duplicate(svc):
    """Retitling renames the file without leaving a duplicate."""
    load(svc, NOTES[:1])
    export.export_vault(svc)
    iid = svc.conn.execute("SELECT id FROM knowledge_items LIMIT 1").fetchone()["id"]
    knowledge.update_item(svc.conn, iid, title="Brand new title")
    export.export_vault(svc)
    assert len([p for p in files(svc) if iid in p.name]) == 1


def test_export_never_modifies_db(svc):
    """Export never writes to the database."""
    load(svc)
    svc.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    h = hashlib.sha256(svc.cfg.db_path.read_bytes()).hexdigest()
    t = svc.conn.total_changes
    export.export_vault(svc)
    assert svc.conn.total_changes == t
    svc.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    assert hashlib.sha256(svc.cfg.db_path.read_bytes()).hexdigest() == h


def test_knowledge_readable_with_all_backends_removed(svc):
    """Exported knowledge needs no backend to read."""
    load(svc)
    svc.cfg.backends, svc.cfg.tasks = {}, {}
    export.export_vault(svc)  # needs no model of any kind
    text = " ".join(p.read_text() for p in files(svc))
    assert "Quokkas" in text and "Sourdough" in text
