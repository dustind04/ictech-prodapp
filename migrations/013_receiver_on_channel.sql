-- =============================================================
-- 013 — the channel's receiver is real hardware, not a protocol
-- =============================================================
-- The old "Shure receiver type" field was micboard's 5-value protocol
-- enum. Operators should pick the actual unit (ULXD4D...) from the
-- catalog; the protocol family (shure_type) is now derived from that
-- choice server-side for the polling worker, no longer hand-entered.

ALTER TABLE channel ADD COLUMN receiver_model_id INTEGER REFERENCES wireless_model(id);
