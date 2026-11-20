-- Contextual desk groups are independent of shelves and never own their notes.
CREATE TABLE desk_state (
  singleton INTEGER PRIMARY KEY CHECK (singleton=1),
  revision INTEGER NOT NULL DEFAULT 0
);
INSERT INTO desk_state(singleton, revision) VALUES (1, 0);
CREATE TABLE desk_groups (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  icon TEXT NOT NULL DEFAULT 'bookmark',
  position INTEGER NOT NULL,
  focused INTEGER NOT NULL DEFAULT 0 CHECK (focused IN (0,1))
);
CREATE TABLE desk_group_items (
  group_id TEXT NOT NULL REFERENCES desk_groups(id) ON DELETE CASCADE,
  item_id TEXT NOT NULL REFERENCES knowledge_items(id),
  position INTEGER NOT NULL,
  PRIMARY KEY (group_id,item_id)
);
