-- =============================================================
-- 008 — backline tech tables
-- =============================================================
-- The parts of Dave's weekly workbook the slot board doesn't show:
-- the full patch list (Input List sheet, all ~40 rows) and the
-- hand-typed islands of the MyMix sheet (IEM RF assignments, the
-- 16-channel MyMix legend, personal-mixer ownership). All four are
-- weekly truth: the importer clears and reloads them on every apply.
-- They feed the /backline engineer dashboard.

CREATE TABLE patch_row (
    id          INTEGER PRIMARY KEY,
    sort_order  INTEGER NOT NULL,
    snake_ch    TEXT,               -- 'Drum 1', 'HL 1'
    foh_ch      INTEGER,            -- console channel
    instrument  TEXT,               -- 'Kick Hi', 'Chris Vox'
    mic         TEXT,               -- 'SM 91', 'Avalon DI', 'Red HH'
    phantom     INTEGER NOT NULL DEFAULT 0 CHECK (phantom IN (0, 1)),
    mute_grp    TEXT,
    mymix_ch    TEXT,               -- 'Drums', 'Vox 1'
    mymix_num   INTEGER,            -- MyMix input number (MyMix sheet H)
    mymix_route TEXT,               -- 'Mtx 1', 'Dir Out' (MyMix sheet I)
    info        TEXT                -- 'Mic Stand', 'No Pad/Flat res', ...
);

CREATE TABLE iem_rf (
    id          INTEGER PRIMARY KEY,
    sort_order  INTEGER NOT NULL,
    iem         TEXT NOT NULL,      -- 'IEM 1'
    rf          TEXT,               -- 'L-14'
    path        TEXT,               -- 'BOH Tio 1'
    owner       TEXT                -- 'Chris Vox'
);

CREATE TABLE mymix_channel (
    id          INTEGER PRIMARY KEY,
    ch          INTEGER NOT NULL,   -- 1..16 (the knobs on every MyMix)
    label       TEXT,               -- 'Drums', 'Click'
    source      TEXT                -- 'Mtx 1', 'Dir Out'
);

CREATE TABLE mymix_mixer (
    id          INTEGER PRIMARY KEY,
    sort_order  INTEGER NOT NULL,
    mixer       TEXT NOT NULL,      -- 'Drums', 'Elec 1'
    owner       TEXT                -- 'Kyle', 'Chip' (blank = unowned)
);
