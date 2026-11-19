-- words the user added after saving (reason / what to keep); user_context also holds adapter provenance
ALTER TABLE inbox_items ADD COLUMN user_note TEXT;
