-- =============================================================
-- 003 — add MyMix channel to slot
-- =============================================================
-- MyMix is the personal-monitor mixing system. Each musician has a
-- physical MyMix device on stage where they dial their own mix.
-- The MyMix channel is the label they see on their device for their
-- own voice/instrument feed -- e.g. "Vox 1" or "Misc".
--
-- It varies per service (different singer in slot 1 may be on a
-- different MyMix channel depending on FOH routing), so it lives
-- on the slot, not the channel.
-- =============================================================

ALTER TABLE slot ADD COLUMN mymix_channel TEXT;
