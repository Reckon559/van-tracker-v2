USE van_tracker_v2;

ALTER TABLE trips
    ADD COLUMN scenario_traffic_level ENUM('low', 'medium', 'high')
        NOT NULL DEFAULT 'medium' AFTER heading_deg,
    ADD COLUMN scenario_weather ENUM('clear', 'rain', 'heavy_rain', 'fog')
        NOT NULL DEFAULT 'clear' AFTER scenario_traffic_level,
    ADD COLUMN scenario_school_period ENUM('regular', 'exam', 'half_day')
        NOT NULL DEFAULT 'regular' AFTER scenario_weather,
    ADD COLUMN scenario_hour_of_day TINYINT UNSIGNED
        NOT NULL DEFAULT 8 AFTER scenario_school_period,
    ADD COLUMN scenario_day_of_week TINYINT UNSIGNED
        NOT NULL DEFAULT 0 AFTER scenario_hour_of_day,
    ADD COLUMN route_road_type VARCHAR(50)
        NOT NULL DEFAULT 'unclassified' AFTER scenario_day_of_week,
    ADD COLUMN baseline_duration_sec DECIMAL(10,2) NULL
        AFTER route_road_type,
    ADD COLUMN predicted_eta_sec DECIMAL(10,2) NULL
        AFTER baseline_duration_sec,
    ADD COLUMN predicted_eta_lower_sec DECIMAL(10,2) NULL
        AFTER predicted_eta_sec,
    ADD COLUMN predicted_eta_upper_sec DECIMAL(10,2) NULL
        AFTER predicted_eta_lower_sec,
    ADD COLUMN eta_model_version VARCHAR(80) NULL
        AFTER predicted_eta_upper_sec;

ALTER TABLE trip_telemetry
    ADD COLUMN predicted_remaining_sec DECIMAL(10,2) NULL
        AFTER actual_remaining_sec;
