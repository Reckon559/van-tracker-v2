USE van_tracker_v2;

ALTER TABLE trips
    ADD COLUMN reached_stop_count SMALLINT UNSIGNED NOT NULL DEFAULT 0
        AFTER distance_travelled_m,
    ADD COLUMN heading_deg DECIMAL(6,2) NOT NULL DEFAULT 0.00
        AFTER reached_stop_count;

ALTER TABLE trip_stops
    ADD COLUMN route_distance_m DECIMAL(12,2) NULL
        AFTER stop_lng;
