USE van_tracker_v2;

CREATE TABLE IF NOT EXISTS trip_attendance (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    trip_id BIGINT UNSIGNED NOT NULL,
    student_id BIGINT UNSIGNED NOT NULL,
    status ENUM('pending', 'boarded') NOT NULL DEFAULT 'pending',
    marked_by_driver_id BIGINT UNSIGNED NULL,
    marked_at DATETIME NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_trip_attendance_student (trip_id, student_id),
    INDEX idx_attendance_trip_status (trip_id, status),
    CONSTRAINT fk_attendance_trip
        FOREIGN KEY (trip_id) REFERENCES trips(id) ON DELETE CASCADE,
    CONSTRAINT fk_attendance_student
        FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE,
    CONSTRAINT fk_attendance_driver
        FOREIGN KEY (marked_by_driver_id) REFERENCES drivers(id) ON DELETE SET NULL
) ENGINE=InnoDB;

ALTER TABLE notifications
    MODIFY type ENUM(
        'trip_started', 'eta_update', 'near_stop', 'arrived',
        'emergency_stop', 'overspeed', 'long_stop',
        'route_deviation', 'attendance_missing', 'trip_completed'
    ) NOT NULL;

ALTER TABLE anomaly_events
    MODIFY anomaly_type ENUM(
        'route_deviation', 'long_stop', 'emergency_stop', 'overspeed',
        'attendance_missing'
    ) NOT NULL;

ALTER TABLE simulation_events
    MODIFY event_type ENUM(
        'trip_started', 'pause', 'resume', 'playback_change',
        'traffic_change', 'weather_change', 'student_stop',
        'incident', 'emergency_stop', 'manual_speed_change',
        'route_deviation', 'route_return', 'obstacle', 'obstacle_cleared',
        'attendance_missing'
    ) NOT NULL;
