CREATE TABLE channel_state (
  channel TEXT NOT NULL,
  key TEXT NOT NULL,
  value TEXT NOT NULL,
  PRIMARY KEY (channel, key)
);
