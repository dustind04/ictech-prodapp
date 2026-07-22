-- =============================================================
-- 015 — build-your-own dashboards
-- =============================================================
-- A dashboard is a named, ordered arrangement of widgets (slot
-- zones, patch table, clock, notes, ...) served TV-ready at
-- /d/<slug> and offered on the /tv picker. `config` is JSON:
--   {"widgets": [{"type": "patch", "width": "full", "opts": {}}]}
-- Widget vocabulary lives in app.py (DASH_WIDGETS) — the table
-- stays dumb on purpose.

CREATE TABLE dashboard (
    id          INTEGER PRIMARY KEY,
    slug        TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    config      TEXT NOT NULL DEFAULT '{"widgets": []}',
    archived    INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
