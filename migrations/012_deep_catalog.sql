-- =============================================================
-- 012 — deep catalog: legacy Shure families, specialty
--       transmitters, and the Countryman lav/headset line
-- =============================================================
-- "All the options I'd ever need": classic ULX (ULX1/ULX2/ULXS4/
-- ULXP4), legacy SLX / PGX / PGX-D / original GLX-D, ULX-D specialty
-- transmitters (boundary + gooseneck), PSM 700; and Countryman
-- earsets/lavs/headsets as a third capsule brand — they hang off mic
-- beltpacks the same way handheld capsules hang off transmitters.
-- Both tables are FK parents of channel: rebuilds run with FKs off
-- and are re-runnable (see 011's lesson).

PRAGMA foreign_keys = OFF;

-- ---- wireless_model: add 'specialty' kind -------------------
DROP TABLE IF EXISTS wireless_model_new;
CREATE TABLE wireless_model_new (
    id          INTEGER PRIMARY KEY,
    brand       TEXT NOT NULL DEFAULT 'Shure',
    family      TEXT NOT NULL,
    model       TEXT NOT NULL,
    kind        TEXT NOT NULL CHECK (kind IN
                  ('handheld', 'beltpack', 'iem', 'receiver', 'iem_tx',
                   'plugon', 'specialty')),
    sort_order  INTEGER NOT NULL DEFAULT 100,
    UNIQUE (brand, model)
);
INSERT INTO wireless_model_new (id, brand, family, model, kind, sort_order)
    SELECT id, brand, family, model, kind, sort_order FROM wireless_model;
DROP TABLE wireless_model;
ALTER TABLE wireless_model_new RENAME TO wireless_model;

INSERT INTO wireless_model (family, model, kind, sort_order) VALUES
    -- original GLX-D (2.4 GHz, pre-'+')
    ('GLX-D (legacy)', 'GLXD1',  'beltpack', 52),
    ('GLX-D (legacy)', 'GLXD2',  'handheld', 52),
    ('GLX-D (legacy)', 'GLXD4',  'receiver', 52),
    -- PGX-D
    ('PGX-D', 'PGXD1', 'beltpack', 55),
    ('PGX-D', 'PGXD2', 'handheld', 55),
    ('PGX-D', 'PGXD4', 'receiver', 55),
    -- PGX (analog legacy)
    ('PGX (legacy)', 'PGX1', 'beltpack', 70),
    ('PGX (legacy)', 'PGX2', 'handheld', 70),
    ('PGX (legacy)', 'PGX4', 'receiver', 70),
    -- SLX (analog legacy, pre-SLX-D)
    ('SLX (legacy)', 'SLX1', 'beltpack', 72),
    ('SLX (legacy)', 'SLX2', 'handheld', 72),
    ('SLX (legacy)', 'SLX4', 'receiver', 72),
    -- original ULX (analog): standard + professional receivers
    ('ULX (legacy)', 'ULX1',  'beltpack', 74),
    ('ULX (legacy)', 'ULX2',  'handheld', 74),
    ('ULX (legacy)', 'ULXS4', 'receiver', 74),
    ('ULX (legacy)', 'ULXP4', 'receiver', 75),
    -- ULX-D specialty transmitters (pulpit / choir / boundary)
    ('ULX-D', 'ULXD6', 'specialty', 20),
    ('ULX-D', 'ULXD8', 'specialty', 21),
    -- PSM 700 (legacy IEM)
    ('PSM 700', 'P7T', 'iem_tx', 25),
    ('PSM 700', 'P7R', 'iem',    25);

-- ---- capsule_model: add Countryman as a brand ----------------
DROP TABLE IF EXISTS capsule_model_new;
CREATE TABLE capsule_model_new (
    id          INTEGER PRIMARY KEY,
    brand       TEXT NOT NULL CHECK (brand IN ('Shure', 'Sennheiser', 'Countryman')),
    model       TEXT NOT NULL,
    description TEXT,
    part_number TEXT,
    sort_order  INTEGER NOT NULL DEFAULT 100,
    UNIQUE (brand, model)
);
INSERT INTO capsule_model_new (id, brand, model, description, part_number, sort_order)
    SELECT id, brand, model, description, part_number, sort_order FROM capsule_model;
DROP TABLE capsule_model;
ALTER TABLE capsule_model_new RENAME TO capsule_model;

-- Countryman: what actually hangs off the mic beltpacks.
INSERT INTO capsule_model (brand, model, description, sort_order) VALUES
    ('Countryman', 'E6 Earset',      'Earset, omni (directional caps available)', 10),
    ('Countryman', 'E6i Earset',     'Earset, flexible boom, omni',               11),
    ('Countryman', 'E2 Earset',      'Low-profile earset, omni',                  12),
    ('Countryman', 'H6 Headset',     'Dual-ear headset, omni/cardioid options',   20),
    ('Countryman', 'B3 Lavalier',    'Lavalier, omni',                            30),
    ('Countryman', 'B6 Lavalier',    'Micro lavalier, omni',                      31),
    ('Countryman', 'B2D Lavalier',   'Lavalier, directional',                     32),
    ('Countryman', 'EMW Lavalier',   'Classic flat lavalier, omni',               33);

PRAGMA foreign_keys = ON;
