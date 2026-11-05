-- =============================================================
-- 017 — stage spots: where each pool / band seat is on the photo
-- =============================================================
-- Admin → Stage: tap a label (Pool 3, CS Pool, Drums, Speaker...),
-- tap the photo. x/y are percent of the stage image (0,0 = top-left),
-- so they survive any display size. The image itself is a managed
-- file under /photos, named in app_setting 'stage_image' with its
-- aspect in 'stage_ratio' (height / width). No spots = the built-in
-- layout, exactly as before.
CREATE TABLE IF NOT EXISTS stage_spot (
    label   TEXT PRIMARY KEY COLLATE NOCASE,
    x       REAL NOT NULL CHECK (x BETWEEN 0 AND 100),
    y       REAL NOT NULL CHECK (y BETWEEN 0 AND 100)
);
