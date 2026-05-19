-- =============================================================
-- 002 — add stage positions
-- =============================================================
-- A "position" is a named spot on stage where a person stands during
-- service. Examples: "Center Vocal", "Stage Left Vocal", "Pulpit",
-- "Drum Riser". They map roughly to light pools but are managed
-- independently from the lighting system; we just need to tell
-- singers where to stand.
--
-- Positions are assigned to slots, the same way people and channels are.
-- A slot can have a position with or without a person; a person can
-- be in a slot with no position (e.g. a host who roams).
-- =============================================================

CREATE TABLE position (
    id              INTEGER PRIMARY KEY,
    label           TEXT NOT NULL,         -- "Center Vocal", "Pulpit"
    archived        INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_position_archived ON position(archived);

ALTER TABLE slot ADD COLUMN position_id INTEGER REFERENCES position(id) ON DELETE SET NULL;
