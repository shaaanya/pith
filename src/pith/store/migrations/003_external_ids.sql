CREATE TABLE external_ids (
  adapter TEXT NOT NULL,
  external_id TEXT NOT NULL,
  inbox_id TEXT NOT NULL REFERENCES inbox_items(id),
  PRIMARY KEY (adapter, external_id)
);
INSERT INTO external_ids(adapter, external_id, inbox_id)
  SELECT adapter, external_id, id FROM inbox_items WHERE external_id IS NOT NULL
