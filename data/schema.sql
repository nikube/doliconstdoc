CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT
);

CREATE TABLE IF NOT EXISTS constants (
  name TEXT PRIMARY KEY,
  type TEXT,
  default_value TEXT,
  module TEXT,
  purpose TEXT,
  description TEXT,
  impact TEXT,
  possible_values TEXT,
  hidden_setting INTEGER DEFAULT 0,
  hidden_setting_guess INTEGER DEFAULT 0,
  admin_ui_files TEXT,
  doc_quality INTEGER DEFAULT 0,
  content_hash TEXT,
  hash_version TEXT,
  last_enriched TIMESTAMP,
  evidence TEXT,
  confidence TEXT,
  conf_php_wiring TEXT
);

CREATE TABLE IF NOT EXISTS occurrences (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  const_name TEXT REFERENCES constants(name),
  file TEXT,
  line INTEGER,
  usage_type TEXT,
  context TEXT
);

CREATE TABLE IF NOT EXISTS comments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  const_name TEXT REFERENCES constants(name),
  file TEXT,
  line INTEGER,
  text TEXT
);

CREATE INDEX IF NOT EXISTS idx_occ_const ON occurrences(const_name);
CREATE INDEX IF NOT EXISTS idx_comments_const ON comments(const_name);
CREATE INDEX IF NOT EXISTS idx_const_module ON constants(module);
CREATE INDEX IF NOT EXISTS idx_const_quality ON constants(doc_quality);
CREATE INDEX IF NOT EXISTS idx_const_hidden ON constants(hidden_setting);
