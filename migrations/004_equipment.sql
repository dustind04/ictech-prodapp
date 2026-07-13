-- =============================================================
-- 004 — equipment catalog: Shure wireless models + mic capsules
-- =============================================================
-- Immanuel runs Shure wireless exclusively; handheld capsules are
-- Shure and Sennheiser. These reference tables feed the admin
-- dropdowns so a channel can be described by real gear instead of
-- free text. The old channel.capsule column stays — it's the
-- human tag ("Red HH") a singer reads off the rack, not the gear.
--
-- Seeded from the current (mid-2026) catalogs, including SLX-D+
-- (NAMM 2026) and the Nexadyne wireless capsules. Add rows as new
-- gear ships; never delete rows that channels reference.

CREATE TABLE wireless_model (
    id          INTEGER PRIMARY KEY,
    brand       TEXT NOT NULL DEFAULT 'Shure',
    family      TEXT NOT NULL,      -- 'Axient Digital', 'ULX-D', 'PSM 1000', ...
    model       TEXT NOT NULL,      -- transmitter / pack model: 'ULXD2', 'P10R+'
    kind        TEXT NOT NULL CHECK (kind IN ('handheld', 'beltpack', 'iem')),
    sort_order  INTEGER NOT NULL DEFAULT 100,
    UNIQUE (brand, model)
);

CREATE TABLE capsule_model (
    id          INTEGER PRIMARY KEY,
    brand       TEXT NOT NULL CHECK (brand IN ('Shure', 'Sennheiser')),
    model       TEXT NOT NULL,
    description TEXT,               -- transducer + polar pattern
    part_number TEXT,               -- Shure RPW wireless-cartridge part, where applicable
    sort_order  INTEGER NOT NULL DEFAULT 100,
    UNIQUE (brand, model)
);

ALTER TABLE channel ADD COLUMN wireless_model_id INTEGER REFERENCES wireless_model(id);
ALTER TABLE channel ADD COLUMN capsule_model_id  INTEGER REFERENCES capsule_model(id);

-- ---- Shure wireless: handheld transmitters ------------------
INSERT INTO wireless_model (family, model, kind, sort_order) VALUES
    ('Axient Digital', 'AD2',    'handheld', 10),
    ('Axient Digital', 'ADX2',   'handheld', 11),
    ('Axient Digital', 'ADX2FD', 'handheld', 12),
    ('ULX-D',          'ULXD2',  'handheld', 20),
    ('QLX-D',          'QLXD2',  'handheld', 30),
    ('SLX-D',          'SLXD2',  'handheld', 40),
    ('SLX-D+',         'SLXD2+', 'handheld', 41),
    ('GLX-D+',         'GLXD2+', 'handheld', 50),
    ('BLX',            'BLX2',   'handheld', 60),
    ('UHF-R (legacy)', 'UR2',    'handheld', 90);

-- ---- Shure wireless: bodypack transmitters ------------------
INSERT INTO wireless_model (family, model, kind, sort_order) VALUES
    ('Axient Digital', 'AD1',    'beltpack', 10),
    ('Axient Digital', 'ADX1',   'beltpack', 11),
    ('Axient Digital', 'ADX1M',  'beltpack', 12),
    ('ULX-D',          'ULXD1',  'beltpack', 20),
    ('QLX-D',          'QLXD1',  'beltpack', 30),
    ('SLX-D',          'SLXD1',  'beltpack', 40),
    ('GLX-D+',         'GLXD1+', 'beltpack', 50),
    ('BLX',            'BLX1',   'beltpack', 60),
    ('UHF-R (legacy)', 'UR1',    'beltpack', 90),
    ('UHF-R (legacy)', 'UR1M',   'beltpack', 91);

-- ---- Shure IEM bodypack receivers ---------------------------
INSERT INTO wireless_model (family, model, kind, sort_order) VALUES
    ('PSM 1000', 'P10R+', 'iem', 10),
    ('PSM 900',  'P9RA',  'iem', 20),
    ('PSM 300',  'P3R',   'iem', 30);

-- ---- Shure capsules (RPW wireless cartridges) ---------------
INSERT INTO capsule_model (brand, model, description, part_number, sort_order) VALUES
    ('Shure', 'SM58',          'Dynamic cardioid',                        'RPW112', 10),
    ('Shure', 'SM86',          'Condenser cardioid',                      'RPW114', 11),
    ('Shure', 'SM87A',         'Condenser supercardioid',                 'RPW116', 12),
    ('Shure', 'Beta 58A',      'Dynamic supercardioid',                   'RPW118', 20),
    ('Shure', 'Beta 87A',      'Condenser supercardioid',                 'RPW120', 21),
    ('Shure', 'Beta 87C',      'Condenser cardioid',                      'RPW122', 22),
    ('Shure', 'VP68',          'Condenser omnidirectional',               'RPW124', 30),
    ('Shure', 'KSM8 Dualdyne', 'Dynamic cardioid',                        'RPW174', 40),
    ('Shure', 'KSM9',          'Condenser, switchable card/supercard',    'RPW184', 41),
    ('Shure', 'KSM9HS',        'Condenser, switchable hyper/subcardioid', NULL,     42),
    ('Shure', 'KSM11',         'Condenser cardioid',                      'RPW192', 43),
    ('Shure', 'Nexadyne 8/C',  'Dynamic cardioid, dual-engine',           'RPW200', 50),
    ('Shure', 'Nexadyne 8/S',  'Dynamic supercardioid, dual-engine',      'RPW204', 51);

-- ---- Sennheiser capsules (evolution-thread modules) ---------
INSERT INTO capsule_model (brand, model, description, part_number, sort_order) VALUES
    ('Sennheiser', 'MMD 835-1', 'Dynamic cardioid',                          NULL, 10),
    ('Sennheiser', 'MMD 845-1', 'Dynamic supercardioid',                     NULL, 11),
    ('Sennheiser', 'MMD 935-1', 'Dynamic cardioid',                          NULL, 12),
    ('Sennheiser', 'MMD 945-1', 'Dynamic supercardioid',                     NULL, 13),
    ('Sennheiser', 'MMD 42-1',  'Dynamic omnidirectional',                   NULL, 14),
    ('Sennheiser', 'MME 865-1', 'Condenser supercardioid',                   NULL, 20),
    ('Sennheiser', 'MMK 965-1', 'Condenser LD, switchable card/supercard',   NULL, 21),
    ('Sennheiser', 'MD 9235',   'Dynamic cardioid (Digital 6000/9000)',      NULL, 30);
