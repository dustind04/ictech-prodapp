-- =============================================================
-- 007 — band seats on the display
-- =============================================================
-- Everyone named on Dave's input list gets a spot on the wall, not
-- just the wireless mic slots. New slot kind 'band' (bank_order
-- 11-16): a band member with an instrument label, optionally an IEM
-- pack and a MyMix channel. No mic unless one is actually assigned
-- (music leaders leading from an instrument will have one).
--
-- Display order is by group, not bank_order: paired (1-6) left,
-- band (11-16) middle, mic_only (7-10) right.
--
-- SQLite can't ALTER a CHECK constraint, so rebuild the table. The
-- iem CHECK widens too: band seats may carry an IEM pack.

CREATE TABLE slot_new (
    id              INTEGER PRIMARY KEY,
    bank_order      INTEGER NOT NULL UNIQUE CHECK (bank_order BETWEEN 1 AND 20),
    kind            TEXT NOT NULL CHECK (kind IN ('paired', 'mic_only', 'band')),
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

-- Six band seats with the instruments off Dave's input list as
-- starting labels; editable in the slots admin.
INSERT INTO slot (bank_order, kind, label) VALUES
    (11, 'band', 'Drums'),
    (12, 'band', 'Bass'),
    (13, 'band', 'Keys'),
    (14, 'band', 'Elec 1'),
    (15, 'band', 'Acous'),
    (16, 'band', 'Synth');
