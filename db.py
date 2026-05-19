"""
SQLite plumbing for the icTech Services app.

Two responsibilities:
1.  init_db(path) -- at startup, ensure the DB file exists, the migrations
    table exists, and every SQL file in migrations/ has been applied.
    Idempotent: re-running on a fully-migrated DB does nothing.
2.  get_db(path) / close_db() -- per-request connection lifecycle for Flask.
    Uses Flask's `g` to keep one connection per request, returned to the
    teardown handler.

The migration scheme is deliberately primitive: numeric prefix on filename,
applied in order, recorded in a `schema_migrations` table. No down migrations,
no out-of-order detection. Add SQL files in order; do not edit applied ones.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from flask import g


log = logging.getLogger("ictech.db")


def init_db(db_path: str) -> None:
    """Create DB file and apply outstanding migrations. Idempotent."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS schema_migrations (
                 filename TEXT PRIMARY KEY,
                 applied_at TEXT NOT NULL DEFAULT (datetime('now'))
               )"""
        )
        applied = {r["filename"] for r in conn.execute("SELECT filename FROM schema_migrations")}

        migrations_dir = Path(__file__).parent / "migrations"
        for sql_file in sorted(migrations_dir.glob("*.sql")):
            if sql_file.name in applied:
                continue
            log.info("Applying migration: %s", sql_file.name)
            conn.executescript(sql_file.read_text())
            conn.execute("INSERT INTO schema_migrations (filename) VALUES (?)", (sql_file.name,))
            conn.commit()
    finally:
        conn.close()


def get_db(db_path: str | None = None) -> sqlite3.Connection:
    """Return the per-request DB connection, creating it on first call."""
    if "db" not in g:
        path = db_path or _resolve_db_path()
        g.db = sqlite3.connect(path)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db() -> None:
    """Close the per-request DB connection if one was opened."""
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def _resolve_db_path() -> str:
    """Fallback when get_db is called without an explicit path."""
    from flask import current_app
    return current_app.config["DATABASE_PATH"]
