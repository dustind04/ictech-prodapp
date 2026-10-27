-- =============================================================
-- 016 — live telemetry: SLX-D speaks the protocol too
-- =============================================================
-- The receiver poller (shure_live.py) learns SLX-D / SLX-D+, so
-- shure_type gains 'slxd'. Widening a CHECK means rebuilding channel
-- (SQLite). slot and asset reference channel by name, so with FK
-- enforcement off the swap is invisible to them; ids are preserved.
--
-- Also: the full SLX-D+ line (2026) — receivers and the TXs 004
-- didn't have — and a backfill so channels that already picked an
-- SLX-D receiver start polling without a re-save.

PRAGMA foreign_keys = OFF;
DROP TABLE IF EXISTS channel_new;

CREATE TABLE channel_new (
    id              INTEGER PRIMARY KEY,
    label           TEXT NOT NULL,
    kind            TEXT NOT NULL CHECK (kind IN ('handheld', 'beltpack', 'iem')),
    shure_ip        TEXT,
    shure_channel   INTEGER CHECK (shure_channel IS NULL OR shure_channel BETWEEN 1 AND 8),
    shure_type      TEXT CHECK (shure_type IS NULL OR shure_type IN (
                       'qlxd', 'ulxd', 'axtd', 'p10t', 'uhfr', 'slxd'
                    )),
    capsule         TEXT,
    frequency_mhz   REAL,
    archived        INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    wireless_model_id  INTEGER REFERENCES wireless_model(id),
    capsule_model_id   INTEGER REFERENCES capsule_model(id),
    shure_channel_name TEXT,
    receiver_model_id  INTEGER REFERENCES wireless_model(id),
    UNIQUE(shure_ip, shure_channel, archived)
);

INSERT INTO channel_new
    (id, label, kind, shure_ip, shure_channel, shure_type, capsule,
     frequency_mhz, archived, created_at, updated_at, wireless_model_id,
     capsule_model_id, shure_channel_name, receiver_model_id)
SELECT id, label, kind, shure_ip, shure_channel, shure_type, capsule,
       frequency_mhz, archived, created_at, updated_at, wireless_model_id,
       capsule_model_id, shure_channel_name, receiver_model_id
  FROM channel;

DROP TABLE channel;
ALTER TABLE channel_new RENAME TO channel;
CREATE INDEX idx_channel_archived ON channel(archived);
CREATE INDEX idx_channel_shure ON channel(shure_ip, shure_channel);

INSERT OR IGNORE INTO wireless_model (brand, family, model, kind, sort_order) VALUES
    ('Shure', 'SLX-D+', 'SLXD4+',     'receiver', 43),
    ('Shure', 'SLX-D+', 'SLXD4D+',    'receiver', 44),
    ('Shure', 'SLX-D+', 'SLXD4Q+',    'receiver', 45),
    ('Shure', 'SLX-D+', 'SLXD4QDAN+', 'receiver', 46),
    ('Shure', 'SLX-D+', 'SLXD5+',     'receiver', 47),
    ('Shure', 'SLX-D+', 'SLXD1+',     'beltpack', 41),
    ('Shure', 'SLX-D+', 'SLXD3+',     'plugon',   41);

UPDATE channel SET shure_type = 'slxd'
 WHERE shure_type IS NULL
   AND receiver_model_id IN (SELECT id FROM wireless_model
                              WHERE family IN ('SLX-D', 'SLX-D+'));

PRAGMA foreign_keys = ON;
