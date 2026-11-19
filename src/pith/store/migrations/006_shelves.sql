CREATE TABLE shelves (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  blurb TEXT NOT NULL DEFAULT '',
  todo INTEGER NOT NULL DEFAULT 0,
  done_label TEXT,
  builtin INTEGER NOT NULL DEFAULT 0,
  position INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
INSERT INTO shelves(id,name,blurb,todo,done_label,builtin,position,created_at) VALUES
  ('watch','Watch','Films, shows and videos you meant to see',1,'Watched',1,0,'2026-11-18T00:00:00Z'),
  ('listen','Listen','Music, podcasts and talks',1,'Listened',1,1,'2026-11-18T00:00:00Z'),
  ('read','Read','Books, essays and long reads',1,'Read',1,2,'2026-11-18T00:00:00Z'),
  ('play','Play','Games to play',1,'Played',1,3,'2026-11-18T00:00:00Z'),
  ('try','Try','Tools, repos and apps to try out',1,'Tried',1,4,'2026-11-18T00:00:00Z'),
  ('visit','Visit','Places to go',1,'Visited',1,5,'2026-11-18T00:00:00Z'),
  ('reference','Reference','Knowledge to keep and look up',0,NULL,1,6,'2026-11-18T00:00:00Z'),
  ('other','Other','Not sure yet: needs a home',0,NULL,1,7,'2026-11-18T00:00:00Z');
ALTER TABLE knowledge_items ADD COLUMN shelf_id TEXT;
ALTER TABLE knowledge_items ADD COLUMN placement_by TEXT;
ALTER TABLE knowledge_items ADD COLUMN placement_why TEXT;
ALTER TABLE knowledge_items ADD COLUMN placement_model TEXT;
ALTER TABLE knowledge_items ADD COLUMN placed_at TEXT;
CREATE INDEX idx_items_shelf ON knowledge_items(shelf_id);
