"""SQLite layer — connection management, schema, migrations.

One connection per request (stored on flask.g, closed on teardown).
Schema is initialized once at startup, never per request.
Migrations are additive (CREATE IF NOT EXISTS + ALTER attempts) so an
existing duoweilai.db keeps working unchanged — no data migration.

Note: SQLite forbids ADD COLUMN with a UNIQUE constraint, so the email
migration adds a plain column; only fresh databases get the UNIQUE index.
(The v0.5 server had the same quirk — its UNIQUE ALTER silently failed.)
"""

import sqlite3
from datetime import datetime, timedelta, timezone

from flask import current_app, g

SESSION_MAX_AGE_DAYS = 30
RESET_MAX_AGE_HOURS = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS futures (
    id TEXT PRIMARY KEY, short_id TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL, body TEXT NOT NULL,
    creator TEXT NOT NULL DEFAULT 'Anonymous', creator_id INTEGER,
    created_at TEXT NOT NULL, branches INTEGER DEFAULT 0,
    views INTEGER DEFAULT 0, is_world INTEGER DEFAULT 0,
    category TEXT DEFAULT 'Unknown',
    parent_short_id TEXT, edited_at TEXT);
CREATE TABLE IF NOT EXISTS contributions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, future_id TEXT NOT NULL,
    type TEXT NOT NULL, title TEXT NOT NULL, body TEXT,
    creator TEXT NOT NULL DEFAULT 'Anonymous', author_id INTEGER,
    created_at TEXT NOT NULL, edited_at TEXT);
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL, email TEXT UNIQUE,
    reset_token TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY, user_id INTEGER NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS password_resets (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
    token TEXT UNIQUE NOT NULL, expires_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT, future_id TEXT NOT NULL,
    contribution_id INTEGER, parent_id INTEGER, author_id INTEGER NOT NULL,
    body TEXT NOT NULL, created_at TEXT NOT NULL, edited_at TEXT);
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
    actor_id INTEGER NOT NULL, type TEXT NOT NULL,
    future_short_id TEXT, text TEXT NOT NULL,
    is_read INTEGER DEFAULT 0, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_cf ON contributions(future_id);
CREATE INDEX IF NOT EXISTS idx_cm ON comments(future_id);
CREATE INDEX IF NOT EXISTS idx_nu ON notifications(user_id);
"""

# Indexes on columns that older databases only gain via MIGRATIONS below,
# so they must be created after the ALTERs run.
LATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_fut_cat ON futures(category)",
    "CREATE INDEX IF NOT EXISTS idx_fut_created ON futures(created_at)",
    "CREATE INDEX IF NOT EXISTS idx_fut_parent ON futures(parent_short_id)",
]

# Additive migrations for databases created by older versions.
MIGRATIONS = [
    "ALTER TABLE futures ADD COLUMN creator_id INTEGER",
    "ALTER TABLE contributions ADD COLUMN author_id INTEGER",
    "ALTER TABLE futures ADD COLUMN category TEXT DEFAULT 'Unknown'",
    "ALTER TABLE users ADD COLUMN email TEXT",
    "ALTER TABLE users ADD COLUMN reset_token TEXT",
    # v0.6: branching + editing
    "ALTER TABLE futures ADD COLUMN parent_short_id TEXT",
    "ALTER TABLE futures ADD COLUMN edited_at TEXT",
    "ALTER TABLE contributions ADD COLUMN edited_at TEXT",
    "ALTER TABLE comments ADD COLUMN edited_at TEXT",
]


def get_db():
    """Per-request connection with WAL + busy timeout (thread-safe)."""
    if "db" not in g:
        conn = sqlite3.connect(current_app.config["DB_PATH"], timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        g.db = conn
    return g.db


def close_db(exc=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_db(path):
    """Create schema + run migrations + expire old sessions. Startup only."""
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    for ddl in MIGRATIONS:
        try:
            conn.execute(ddl)
        except sqlite3.OperationalError:
            pass  # column already exists
    for ddl in LATE_INDEXES:
        conn.execute(ddl)
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=SESSION_MAX_AGE_DAYS)).isoformat()
    conn.execute("DELETE FROM sessions WHERE created_at < ?", (cutoff,))
    conn.execute("DELETE FROM password_resets WHERE expires_at < ?", (now.isoformat(),))
    conn.commit()
    conn.close()
