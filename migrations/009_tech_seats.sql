-- =============================================================
-- 009 — tech team seats
-- =============================================================
-- Who's behind the controls, visible to the band from the stage.
-- Tech seats are slots (kind 'tech', bank_order 17-22) so they ride
-- the same admin/API/import machinery; `label` carries the role
-- (FOH, MyMix, ...). Role labels below are provisional until the
-- Planning Center tech export defines the standard positions.
-- SQLite can't ALTER CHECKs, so rebuild (same dance as 007).

CREATE TABLE slot_new (
    id              INTEGER PRIMARY KEY,
    bank_order      INTEGER NOT NULL UNIQUE CHECK (bank_order BETWEEN 1 AND 30),
    kind            TEXT NOT NULL CHECK (kind IN ('paired', 'mic_only', 'band', 'tech')),
    person_id       INTEGER REFERENCES person(id) ON DELETE SET NULL,
    mic_channel_id  INTEGER REFERENCES channel(id) ON DELETE SET NULL,
    iem_channel_id  INTEGER REFERENCES channel(id) ON DELETE SET NULL,
    position_id     INTEGER REFERENCES position(id) ON DELETE SET NULL,
    mymix_channel   TEXT,
    label           TEXT,
    archived        INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    CHECK (kind IN ('paired', 'band') OR iem_channel_id IS NULL)
);

INSERT INTO slot_new (id, bank_order, kind, person_id, mic_channel_id,
                      iem_channel_id, position_id, mymix_channel, label,
                      archived, updated_at)
    SELECT id, bank_order, kind, person_id, mic_channel_id,
           iem_channel_id, position_id, mymix_channel, label,
           archived, updated_at
      FROM slot;

DROP TABLE slot;
ALTER TABLE slot_new RENAME TO slot;
CREATE INDEX idx_slot_bank_order ON slot(bank_order);

INSERT INTO slot (bank_order, kind, label) VALUES
    (17, 'tech', 'FOH'),
    (18, 'tech', 'MyMix'),
    (19, 'tech', 'Lyrics'),
    (20, 'tech', 'Cameras'),
    (21, 'tech', 'Lights'),
    (22, 'tech', 'Stream');
