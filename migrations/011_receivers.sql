-- =============================================================
-- 011 — the rest of the Shure hardware: receivers, IEM rack
--       transmitters, plug-ons
-- =============================================================
-- 004 seeded what performers hold (transmitters, IEM bodypacks) but
-- none of the rack: receivers (ULXD4 / ULXD4D / ULXD4Q and friends),
-- PSM rack transmitters, plug-on transmitters. Widening the kind
-- CHECK needs a rebuild (SQLite). The channel table is empty at
-- migration time (stub purge), so no FK rows are at risk; the table
-- name is restored so channel's FK reference stays valid.

CREATE TABLE wireless_model_new (
    id          INTEGER PRIMARY KEY,
    brand       TEXT NOT NULL DEFAULT 'Shure',
    family      TEXT NOT NULL,
    model       TEXT NOT NULL,
    kind        TEXT NOT NULL CHECK (kind IN
                  ('handheld', 'beltpack', 'iem', 'receiver', 'iem_tx', 'plugon')),
    sort_order  INTEGER NOT NULL DEFAULT 100,
    UNIQUE (brand, model)
);

INSERT INTO wireless_model_new (id, brand, family, model, kind, sort_order)
    SELECT id, brand, family, model, kind, sort_order FROM wireless_model;

DROP TABLE wireless_model;
ALTER TABLE wireless_model_new RENAME TO wireless_model;

-- ---- Receivers ----------------------------------------------
INSERT INTO wireless_model (family, model, kind, sort_order) VALUES
    ('Axient Digital', 'AD4D',   'receiver', 10),
    ('Axient Digital', 'AD4Q',   'receiver', 11),
    ('ULX-D',          'ULXD4',  'receiver', 20),
    ('ULX-D',          'ULXD4D', 'receiver', 21),
    ('ULX-D',          'ULXD4Q', 'receiver', 22),
    ('QLX-D',          'QLXD4',  'receiver', 30),
    ('SLX-D',          'SLXD4',  'receiver', 40),
    ('SLX-D',          'SLXD4D', 'receiver', 41),
    ('SLX-D',          'SLXD5',  'receiver', 42),
    ('GLX-D+',         'GLXD4+', 'receiver', 50),
    ('BLX',            'BLX4',   'receiver', 60),
    ('BLX',            'BLX4R',  'receiver', 61),
    ('BLX',            'BLX88',  'receiver', 62),
    ('UHF-R (legacy)', 'UR4S',   'receiver', 90),
    ('UHF-R (legacy)', 'UR4D',   'receiver', 91);

-- ---- IEM rack transmitters ----------------------------------
INSERT INTO wireless_model (family, model, kind, sort_order) VALUES
    ('PSM 1000', 'P10T', 'iem_tx', 10),
    ('PSM 900',  'P9T',  'iem_tx', 20),
    ('PSM 300',  'P3T',  'iem_tx', 30);

-- ---- Plug-on transmitters -----------------------------------
INSERT INTO wireless_model (family, model, kind, sort_order) VALUES
    ('Axient Digital', 'ADX3',  'plugon', 10),
    ('SLX-D',          'SLXD3', 'plugon', 40),
    ('UHF-R (legacy)', 'UR3',   'plugon', 90);
