-- =============================================================
-- 010 — Planning Center position on the slot
-- =============================================================
-- The person's PC plan position for the week ("Acoustic & Vocals",
-- "Bass Guitar", "Host"). Displayed under the name on the wall —
-- redundant most weeks, but consistent for everyone. PC files each
-- person under exactly one position per plan, so this is the
-- "primary role" verbatim; weekly truth like the rest of the slot.

ALTER TABLE slot ADD COLUMN pc_role TEXT;
