-- Per-note state and extracted entries. Keyed by owner = the note's source id (else its own id):
-- reprocess replaces the note row, and a done mark or snooze must survive that.
CREATE TABLE note_state (
  owner TEXT PRIMARY KEY,
  done_at TEXT,
  snooze_until TEXT,
  hidden INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL
);
CREATE TABLE entries (
  id TEXT PRIMARY KEY,
  owner TEXT NOT NULL,
  item_id TEXT NOT NULL,
  text TEXT NOT NULL,
  norm TEXT NOT NULL,
  position INTEGER NOT NULL,
  done_at TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX idx_entries_owner ON entries(owner);
CREATE INDEX idx_entries_item ON entries(item_id);
