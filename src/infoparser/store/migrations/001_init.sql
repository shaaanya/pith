CREATE TABLE inbox_items (
  id TEXT PRIMARY KEY,
  adapter TEXT NOT NULL,
  platform TEXT,
  submitted_at TEXT NOT NULL,
  kind_hint TEXT,
  content_type TEXT,
  payload_text TEXT,
  blob_sha256 TEXT,
  original_filename TEXT,
  mime TEXT,
  canonical_url TEXT,
  user_context TEXT,
  status TEXT NOT NULL CHECK (status IN ('new','pending','processing','processed','failed','needs_clarification')),
  error TEXT,
  attempts INTEGER NOT NULL DEFAULT 0,
  duplicate_of TEXT REFERENCES inbox_items(id),
  source_id TEXT,
  updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX ux_inbox_canonical_url ON inbox_items(canonical_url)
  WHERE canonical_url IS NOT NULL AND duplicate_of IS NULL;
CREATE INDEX ix_inbox_status ON inbox_items(status);
CREATE INDEX ix_inbox_blob ON inbox_items(blob_sha256);

CREATE TABLE jobs (
  id TEXT PRIMARY KEY,
  inbox_id TEXT NOT NULL REFERENCES inbox_items(id),
  kind TEXT NOT NULL DEFAULT 'process',
  state TEXT NOT NULL DEFAULT 'pending' CHECK (state IN ('pending','running','done','failed')),
  attempts INTEGER NOT NULL DEFAULT 0,
  run_after TEXT,
  lease_expires_at TEXT,
  worker_id TEXT,
  last_error TEXT
);
CREATE INDEX ix_jobs_state ON jobs(state, run_after);
CREATE INDEX ix_jobs_inbox ON jobs(inbox_id);

CREATE TABLE processing_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  inbox_id TEXT NOT NULL REFERENCES inbox_items(id),
  job_id TEXT,
  at TEXT NOT NULL,
  stage TEXT NOT NULL,
  status TEXT,
  detail TEXT,
  duration_ms INTEGER,
  backend TEXT,
  model TEXT,
  egress INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX ix_events_inbox ON processing_events(inbox_id);

CREATE TABLE sources (
  id TEXT PRIMARY KEY,
  url TEXT,
  title TEXT,
  author TEXT,
  platform TEXT,
  content_type TEXT,
  fetched_at TEXT,
  blob_sha256 TEXT,
  text_sha256 TEXT,
  extractor TEXT,
  extractor_version TEXT
);
CREATE INDEX ix_sources_url ON sources(url);
CREATE INDEX ix_sources_text_sha ON sources(text_sha256);

CREATE TABLE segments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_id TEXT NOT NULL REFERENCES sources(id),
  idx INTEGER NOT NULL,
  text TEXT NOT NULL,
  locator TEXT,
  UNIQUE (source_id, idx)
);

CREATE TABLE knowledge_items (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  title TEXT,
  body TEXT,
  data_json TEXT,
  provenance TEXT NOT NULL CHECK (provenance IN ('stated','inferred','external')),
  confidence REAL,
  source_id TEXT REFERENCES sources(id),
  segment_refs TEXT,
  extracted_by TEXT,
  user_edited INTEGER NOT NULL DEFAULT 0,
  version INTEGER NOT NULL DEFAULT 1,
  flagged INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  last_viewed_at TEXT,
  deleted_at TEXT
);
CREATE INDEX ix_items_source ON knowledge_items(source_id);

CREATE TABLE knowledge_versions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  item_id TEXT NOT NULL REFERENCES knowledge_items(id),
  version INTEGER NOT NULL,
  title TEXT,
  body TEXT,
  data_json TEXT,
  saved_at TEXT NOT NULL,
  reason TEXT
);

CREATE TABLE topics (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL UNIQUE
);
CREATE TABLE entities (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  type TEXT,
  UNIQUE (name, type)
);
CREATE TABLE item_topics (
  item_id TEXT NOT NULL REFERENCES knowledge_items(id),
  topic_id TEXT NOT NULL REFERENCES topics(id),
  PRIMARY KEY (item_id, topic_id)
);
CREATE TABLE item_entities (
  item_id TEXT NOT NULL REFERENCES knowledge_items(id),
  entity_id TEXT NOT NULL REFERENCES entities(id),
  PRIMARY KEY (item_id, entity_id)
);
CREATE TABLE relations (
  item_a TEXT NOT NULL REFERENCES knowledge_items(id),
  item_b TEXT NOT NULL REFERENCES knowledge_items(id),
  type TEXT NOT NULL,
  score REAL,
  PRIMARY KEY (item_a, item_b, type)
);

CREATE TABLE embeddings (
  owner_type TEXT NOT NULL,
  owner_id TEXT NOT NULL,
  model_id TEXT NOT NULL,
  dim INTEGER NOT NULL,
  vector BLOB NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (owner_type, owner_id, model_id)
);

CREATE TABLE provenance_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_id TEXT,
  inbox_id TEXT,
  url TEXT,
  added_at TEXT NOT NULL
);

-- rowid of each FTS row = segments.id / knowledge_items rowid; callers keep them in sync
CREATE VIRTUAL TABLE segments_fts USING fts5(text);
CREATE VIRTUAL TABLE items_fts USING fts5(title, body)
