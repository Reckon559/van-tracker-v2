USE van_tracker_v2;

ALTER TABLE simulation_events
    MODIFY event_type ENUM(
        'trip_started', 'pause', 'resume', 'playback_change',
        'traffic_change', 'weather_change', 'student_stop',
        'incident', 'emergency_stop', 'manual_speed_change',
        'route_deviation', 'route_return'
    ) NOT NULL;

CREATE TABLE IF NOT EXISTS anomaly_events (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    trip_id BIGINT UNSIGNED NOT NULL,
    anomaly_type ENUM(
        'route_deviation', 'long_stop', 'emergency_stop', 'overspeed'
    ) NOT NULL,
    classification ENUM('normal', 'monitor', 'suspicious') NOT NULL,
    isolation_status VARCHAR(20) NOT NULL,
    isolation_score DECIMAL(10,6) NULL,
    audience ENUM('none', 'staff', 'parent') NOT NULL DEFAULT 'none',
    reason VARCHAR(500) NOT NULL,
    decision_data JSON NULL,
    dedup_key VARCHAR(190) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_anomaly_event_dedup (dedup_key),
    INDEX idx_anomaly_trip (trip_id, id),
    CONSTRAINT fk_anomaly_trip
        FOREIGN KEY (trip_id) REFERENCES trips(id) ON DELETE CASCADE
) ENGINE=InnoDB;
