import sqlite3
from pathlib import Path

SCHEMA = """
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
"""

# Migrations for existing DBs (no-op if columns already exist)
MIGRATIONS = [
    "ALTER TABLE constants ADD COLUMN evidence TEXT",
    "ALTER TABLE constants ADD COLUMN confidence TEXT",
    "ALTER TABLE constants ADD COLUMN conf_php_wiring TEXT",
]


def connect(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    # Best-effort migrations for pre-existing DBs
    for stmt in MIGRATIONS:
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError:
            pass
    conn.commit()
    return conn


def insert_comment(
    conn: sqlite3.Connection,
    const_name: str,
    file: str,
    line: int,
    text: str,
) -> None:
    conn.execute(
        "INSERT INTO comments(const_name, file, line, text) VALUES(?,?,?,?)",
        (const_name, file, line, text),
    )


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def upsert_constant(conn: sqlite3.Connection, name: str, **fields) -> None:
    existing = conn.execute(
        "SELECT 1 FROM constants WHERE name = ?", (name,)
    ).fetchone()
    if existing is None:
        cols = ["name"] + list(fields.keys())
        placeholders = ", ".join("?" * len(cols))
        conn.execute(
            f"INSERT INTO constants({', '.join(cols)}) VALUES({placeholders})",
            [name] + list(fields.values()),
        )
    elif fields:
        sets = ", ".join(f"{k} = ?" for k in fields)
        conn.execute(
            f"UPDATE constants SET {sets} WHERE name = ?",
            list(fields.values()) + [name],
        )


def insert_occurrence(
    conn: sqlite3.Connection,
    const_name: str,
    file: str,
    line: int,
    usage_type: str,
    context: str,
) -> None:
    conn.execute(
        "INSERT INTO occurrences(const_name, file, line, usage_type, context) "
        "VALUES(?, ?, ?, ?, ?)",
        (const_name, file, line, usage_type, context),
    )
