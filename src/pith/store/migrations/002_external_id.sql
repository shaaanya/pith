ALTER TABLE inbox_items ADD COLUMN external_id TEXT;
CREATE UNIQUE INDEX ux_inbox_external ON inbox_items(adapter, external_id)
  WHERE external_id IS NOT NULL
