-- =============================================================
-- 014 — tech asset management
-- =============================================================
-- Every physical thing the tech ministry owns gets a row and a tag
-- (ICT-0001...). The tag is what the printed QR label encodes, so it
-- never changes once a label is stuck on the gear. `channel_id` links
-- a transmitter/IEM asset to its wireless-inventory channel; consoles,
-- receivers, stands, cables, etc. simply leave it NULL.
-- `category` is free text on purpose (the datalist in the form
-- suggests the common ones) — no rebuild dance when a new kind of
-- gear shows up.

CREATE TABLE asset (
    id             INTEGER PRIMARY KEY,
    tag            TEXT NOT NULL UNIQUE,
    name           TEXT NOT NULL,
    category       TEXT NOT NULL DEFAULT 'other',
    brand          TEXT,
    model          TEXT,
    serial_number  TEXT,
    status         TEXT NOT NULL DEFAULT 'in_service'
                   CHECK (status IN ('in_service', 'storage', 'repair',
                                     'loaned', 'missing', 'retired')),
    location       TEXT,
    channel_id     INTEGER REFERENCES channel(id) ON DELETE SET NULL,
    purchase_date  TEXT,
    purchase_price REAL,
    notes          TEXT,
    archived       INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_asset_tag ON asset(tag);
CREATE INDEX idx_asset_status ON asset(status);
