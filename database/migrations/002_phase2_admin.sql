USE van_tracker_v2;

ALTER TABLE routes
    ADD COLUMN IF NOT EXISTS start_name VARCHAR(160) NULL AFTER name,
    ADD COLUMN IF NOT EXISTS start_lat DECIMAL(10,8) NULL AFTER start_name,
    ADD COLUMN IF NOT EXISTS start_lng DECIMAL(11,8) NULL AFTER start_lat;

UPDATE routes
SET
    start_name = COALESCE(start_name, 'Route starting point'),
    start_lat = COALESCE(start_lat, school_lat),
    start_lng = COALESCE(start_lng, school_lng);

ALTER TABLE routes
    MODIFY start_name VARCHAR(160) NOT NULL,
    MODIFY start_lat DECIMAL(10,8) NOT NULL,
    MODIFY start_lng DECIMAL(11,8) NOT NULL;
