-- =============================================================
-- 001 — initial schema for icTech Services
-- =============================================================
-- Three real tables, three concepts:
--
--   person    -- a human who appears on stage (singer, speaker, host)
--   channel   -- a Shure wireless input the system can talk to
--               (a handheld, beltpack, or IEM pack)
--   slot      -- a physical position in the charger bank under the
--               mic-board screen. 10 slots total. Slots 1-6 hold a
--               vocalist's handheld + IEM pair; slots 7-10 hold a
--               wireless beltpack mic only (lavs, headsets, sermon).
--
-- A slot has a person (who's assigned to it for the current service)
-- and one or two channels (their handheld + their IEM, or just the
-- beltpack mic). When no person is assigned, the slot is "empty" and
-- still renders as a placeholder on the wall display.
--
-- The live receiver state (battery, RF, mute) is NOT in this schema
-- because it's ephemeral. It lives in memory in the Shure worker and
-- joins onto these tables at query time by (shure_ip, shure_channel).
-- =============================================================

CREATE TABLE person (
    id              INTEGER PRIMARY KEY,
    display_name    TEXT NOT NULL,         -- "Sarah K."
    nickname        TEXT,                  -- "Sarah" -- preferred over display_name when set
    photo_url       TEXT,                  -- optional avatar; initials fallback if NULL
    archived        INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_person_archived ON person(archived);


CREATE TABLE channel (
    id              INTEGER PRIMARY KEY,
    label           TEXT NOT NULL,         -- "Red HH", "IEM 1", "Bryan Headset"
    kind            TEXT NOT NULL CHECK (kind IN ('handheld', 'beltpack', 'iem')),

    -- How to reach this channel on the network. Combined (shure_ip, shure_channel)
    -- is the key the Shure worker uses to associate live state to this row.
    -- All four columns are optional so the system is usable for planning
    -- before receiver IPs have been entered.
    shure_ip        TEXT,
    shure_channel   INTEGER CHECK (shure_channel IS NULL OR shure_channel BETWEEN 1 AND 8),
    shure_type      TEXT CHECK (shure_type IS NULL OR shure_type IN (
                       'qlxd', 'ulxd', 'axtd', 'p10t', 'uhfr'
                    )),

    -- Physical identifiers visible to staff: capsule color, frequency,
    -- whatever helps a singer pick the right pack off the rack.
    capsule         TEXT,                  -- "Red HH", "White HH", "Headset"
    frequency_mhz   REAL,                  -- optional; we may or may not display

    archived        INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),

    -- A given (ip, channel) pair must be unique among non-archived channels.
    -- We can't easily enforce that with a UNIQUE constraint that respects
    -- archival; the application layer is responsible for validating uniqueness
    -- at write time.
    UNIQUE(shure_ip, shure_channel, archived)
);
CREATE INDEX idx_channel_archived ON channel(archived);
CREATE INDEX idx_channel_shure ON channel(shure_ip, shure_channel);


CREATE TABLE slot (
    id              INTEGER PRIMARY KEY,
    bank_order      INTEGER NOT NULL UNIQUE CHECK (bank_order BETWEEN 1 AND 10),
    kind            TEXT NOT NULL CHECK (kind IN ('paired', 'mic_only')),

    -- Current assignment. NULL person_id = empty slot.
    -- mic_channel_id MUST be a 'handheld' (slots 1-6) or 'beltpack' (slots 7-10).
    -- iem_channel_id is only allowed when kind = 'paired' (slots 1-6).
    -- These constraints are enforced at the application layer, not DB-level,
    -- because SQLite can't express them cleanly with CHECK across joins.
    person_id       INTEGER REFERENCES person(id) ON DELETE SET NULL,
    mic_channel_id  INTEGER REFERENCES channel(id) ON DELETE SET NULL,
    iem_channel_id  INTEGER REFERENCES channel(id) ON DELETE SET NULL,

    -- An optional human label printed on the physical slot sticker, if any.
    label           TEXT,

    archived        INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),

    CHECK (kind = 'paired' OR iem_channel_id IS NULL)
);
CREATE INDEX idx_slot_bank_order ON slot(bank_order);


-- Seed the 10 physical slots so they always render even when nothing is
-- assigned. Slots 1-6 are paired (vocalist handheld + IEM); slots 7-10
-- are mic-only (beltpack lavs/headsets/sermon).
INSERT INTO slot (bank_order, kind) VALUES
    (1, 'paired'),
    (2, 'paired'),
    (3, 'paired'),
    (4, 'paired'),
    (5, 'paired'),
    (6, 'paired'),
    (7, 'mic_only'),
    (8, 'mic_only'),
    (9, 'mic_only'),
    (10, 'mic_only');
