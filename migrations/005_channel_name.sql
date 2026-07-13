-- =============================================================
-- 005 — WWB channel name replaces the numeric channel index in
--       the admin UI
-- =============================================================
-- Wireless Workbench identifies a channel by its channel NAME —
-- that's what shows in WWB, what Dave's weekly docs carry, and what
-- staff actually transcribe. The numeric receiver-channel index
-- (channel.shure_channel) stays in the schema: it's part of a UNIQUE
-- constraint and remains the protocol-level join key for the future
-- live Shure worker, which can resolve name -> index from the device.
-- It just isn't operator-entered anymore.

ALTER TABLE channel ADD COLUMN shure_channel_name TEXT;
