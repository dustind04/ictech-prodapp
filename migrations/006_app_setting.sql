-- =============================================================
-- 006 — app_setting: single-row key/value state
-- =============================================================
-- First use: 'leader_person_id', the person leading music THIS week.
-- It's weekly state like slot assignments (music leaders rotate), but
-- it can't live on slot — the leader may be a band member with no
-- mic-board slot at all (e.g. leading from guitar or keys).

CREATE TABLE app_setting (
    key   TEXT PRIMARY KEY,
    value TEXT
);
