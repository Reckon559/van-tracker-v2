CREATE DATABASE IF NOT EXISTS van_tracker_v2
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE van_tracker_v2;

CREATE TABLE users (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(120) NOT NULL,
    email VARCHAR(190) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    role ENUM('admin', 'driver', 'parent') NOT NULL,
    active TINYINT(1) NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE vans (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    van_number VARCHAR(50) NOT NULL UNIQUE,
    plate_number VARCHAR(50) NOT NULL UNIQUE,
    capacity SMALLINT UNSIGNED NOT NULL DEFAULT 15,
    speed_limit_kmh DECIMAL(5,2) NOT NULL DEFAULT 40.00,
    active TINYINT(1) NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE drivers (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT UNSIGNED NOT NULL UNIQUE,
    van_id BIGINT UNSIGNED NULL UNIQUE,
    phone VARCHAR(30) NOT NULL,
    license_number VARCHAR(80) NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_drivers_user
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT fk_drivers_van
        FOREIGN KEY (van_id) REFERENCES vans(id) ON DELETE SET NULL
) ENGINE=InnoDB;

CREATE TABLE routes (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(120) NOT NULL,
    start_name VARCHAR(160) NOT NULL,
    start_lat DECIMAL(10,8) NOT NULL,
    start_lng DECIMAL(11,8) NOT NULL,
    school_name VARCHAR(160) NOT NULL,
    school_lat DECIMAL(10,8) NOT NULL,
    school_lng DECIMAL(11,8) NOT NULL,
    algorithm ENUM('astar', 'contraction_hierarchy') NOT NULL DEFAULT 'astar',
    active TINYINT(1) NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE students (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(120) NOT NULL,
    parent_id BIGINT UNSIGNED NOT NULL,
    van_id BIGINT UNSIGNED NOT NULL,
    pickup_location VARCHAR(255) NOT NULL,
    pickup_lat DECIMAL(10,8) NOT NULL,
    pickup_lng DECIMAL(11,8) NOT NULL,
    active TINYINT(1) NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_students_parent (parent_id),
    INDEX idx_students_van (van_id),
    CONSTRAINT fk_students_parent
        FOREIGN KEY (parent_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT fk_students_van
        FOREIGN KEY (van_id) REFERENCES vans(id) ON DELETE RESTRICT
) ENGINE=InnoDB;

CREATE TABLE route_students (
    route_id BIGINT UNSIGNED NOT NULL,
    student_id BIGINT UNSIGNED NOT NULL,
    stop_sequence SMALLINT UNSIGNED NULL,
    PRIMARY KEY (route_id, student_id),
    CONSTRAINT fk_route_students_route
        FOREIGN KEY (route_id) REFERENCES routes(id) ON DELETE CASCADE,
    CONSTRAINT fk_route_students_student
        FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE trips (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    route_id BIGINT UNSIGNED NOT NULL,
    van_id BIGINT UNSIGNED NOT NULL,
    driver_id BIGINT UNSIGNED NOT NULL,
    trip_type ENUM('morning', 'afternoon') NOT NULL,
    status ENUM(
        'scheduled', 'active', 'paused', 'emergency',
        'completed', 'cancelled'
    ) NOT NULL DEFAULT 'scheduled',
    started_at DATETIME NULL,
    completed_at DATETIME NULL,
    simulated_elapsed_sec INT UNSIGNED NOT NULL DEFAULT 0,
    current_lat DECIMAL(10,8) NULL,
    current_lng DECIMAL(11,8) NULL,
    physical_speed_kmh DECIMAL(6,2) NOT NULL DEFAULT 0.00,
    playback_multiplier DECIMAL(5,2) NOT NULL DEFAULT 1.00,
    total_distance_m DECIMAL(12,2) NOT NULL DEFAULT 0.00,
    distance_travelled_m DECIMAL(12,2) NOT NULL DEFAULT 0.00,
    reached_stop_count SMALLINT UNSIGNED NOT NULL DEFAULT 0,
    heading_deg DECIMAL(6,2) NOT NULL DEFAULT 0.00,
    scenario_traffic_level ENUM('low', 'medium', 'high') NOT NULL DEFAULT 'medium',
    scenario_weather ENUM('clear', 'rain', 'heavy_rain', 'fog') NOT NULL DEFAULT 'clear',
    scenario_school_period ENUM('regular', 'exam', 'half_day') NOT NULL DEFAULT 'regular',
    scenario_hour_of_day TINYINT UNSIGNED NOT NULL DEFAULT 8,
    scenario_day_of_week TINYINT UNSIGNED NOT NULL DEFAULT 0,
    route_road_type VARCHAR(50) NOT NULL DEFAULT 'unclassified',
    baseline_duration_sec DECIMAL(10,2) NULL,
    predicted_eta_sec DECIMAL(10,2) NULL,
    predicted_eta_lower_sec DECIMAL(10,2) NULL,
    predicted_eta_upper_sec DECIMAL(10,2) NULL,
    eta_model_version VARCHAR(80) NULL,
    random_seed INT UNSIGNED NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_trips_status (status),
    INDEX idx_trips_van (van_id),
    CONSTRAINT fk_trips_route
        FOREIGN KEY (route_id) REFERENCES routes(id) ON DELETE RESTRICT,
    CONSTRAINT fk_trips_van
        FOREIGN KEY (van_id) REFERENCES vans(id) ON DELETE RESTRICT,
    CONSTRAINT fk_trips_driver
        FOREIGN KEY (driver_id) REFERENCES drivers(id) ON DELETE RESTRICT
) ENGINE=InnoDB;

CREATE TABLE trip_stops (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    trip_id BIGINT UNSIGNED NOT NULL,
    student_id BIGINT UNSIGNED NULL,
    stop_order SMALLINT UNSIGNED NOT NULL,
    stop_name VARCHAR(255) NOT NULL,
    stop_lat DECIMAL(10,8) NOT NULL,
    stop_lng DECIMAL(11,8) NOT NULL,
    route_distance_m DECIMAL(12,2) NULL,
    stop_type ENUM('student_home', 'school', 'depot') NOT NULL,
    attendance_status ENUM('unmarked', 'present', 'absent')
        NOT NULL DEFAULT 'unmarked',
    attendance_marked_at DATETIME NULL,
    attendance_marked_by BIGINT UNSIGNED NULL,
    status ENUM('pending', 'arrived', 'skipped') NOT NULL DEFAULT 'pending',
    arrived_at DATETIME NULL,
    UNIQUE KEY uq_trip_stop_order (trip_id, stop_order),
    INDEX idx_trip_stops_attendance (trip_id, attendance_status),
    CONSTRAINT fk_trip_stops_trip
        FOREIGN KEY (trip_id) REFERENCES trips(id) ON DELETE CASCADE,
    CONSTRAINT fk_trip_stops_student
        FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE SET NULL,
    CONSTRAINT fk_trip_stops_attendance_user
        FOREIGN KEY (attendance_marked_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB;

-- One row is recorded every five simulated seconds during data-generation trips.
-- actual_remaining_sec is filled only after the trip finishes.
CREATE TABLE trip_telemetry (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    trip_id BIGINT UNSIGNED NOT NULL,
    sample_index INT UNSIGNED NOT NULL,
    recorded_at DATETIME NOT NULL,
    simulated_time_sec INT UNSIGNED NOT NULL,
    latitude DECIMAL(10,8) NOT NULL,
    longitude DECIMAL(11,8) NOT NULL,
    current_speed_kmh DECIMAL(6,2) NOT NULL,
    speed_limit_kmh DECIMAL(6,2) NOT NULL,
    road_type VARCHAR(50) NOT NULL,
    segment_length_m DECIMAL(10,2) NOT NULL,
    segment_base_time_sec DECIMAL(10,2) NOT NULL,
    traffic_level ENUM('low', 'medium', 'high') NOT NULL,
    traffic_multiplier DECIMAL(5,2) NOT NULL,
    weather ENUM('clear', 'rain', 'heavy_rain', 'fog') NOT NULL,
    weather_multiplier DECIMAL(5,2) NOT NULL,
    stop_delay_sec DECIMAL(8,2) NOT NULL DEFAULT 0.00,
    incident_delay_sec DECIMAL(8,2) NOT NULL DEFAULT 0.00,
    distance_remaining_m DECIMAL(12,2) NOT NULL,
    route_progress DECIMAL(6,5) NOT NULL,
    hour_of_day TINYINT UNSIGNED NOT NULL,
    day_of_week TINYINT UNSIGNED NOT NULL,
    actual_remaining_sec DECIMAL(10,2) NULL,
    predicted_remaining_sec DECIMAL(10,2) NULL,
    UNIQUE KEY uq_trip_sample (trip_id, sample_index),
    INDEX idx_telemetry_trip (trip_id),
    CONSTRAINT fk_telemetry_trip
        FOREIGN KEY (trip_id) REFERENCES trips(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE eta_predictions (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    trip_id BIGINT UNSIGNED NOT NULL,
    student_id BIGINT UNSIGNED NULL,
    predicted_at DATETIME NOT NULL,
    destination_lat DECIMAL(10,8) NOT NULL,
    destination_lng DECIMAL(11,8) NOT NULL,
    predicted_eta_sec DECIMAL(10,2) NOT NULL,
    model_version VARCHAR(80) NOT NULL,
    CONSTRAINT fk_eta_trip
        FOREIGN KEY (trip_id) REFERENCES trips(id) ON DELETE CASCADE,
    CONSTRAINT fk_eta_student
        FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE SET NULL
) ENGINE=InnoDB;

CREATE TABLE notifications (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    parent_id BIGINT UNSIGNED NOT NULL,
    student_id BIGINT UNSIGNED NULL,
    trip_id BIGINT UNSIGNED NULL,
    type ENUM(
        'trip_started', 'eta_update', 'near_stop', 'arrived',
        'emergency_stop', 'overspeed', 'long_stop',
        'route_deviation', 'trip_completed'
    ) NOT NULL,
    message VARCHAR(500) NOT NULL,
    dedup_key VARCHAR(190) NULL,
    is_read TINYINT(1) NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_notification_dedup (dedup_key),
    INDEX idx_notifications_parent (parent_id, id),
    CONSTRAINT fk_notifications_parent
        FOREIGN KEY (parent_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT fk_notifications_student
        FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE SET NULL,
    CONSTRAINT fk_notifications_trip
        FOREIGN KEY (trip_id) REFERENCES trips(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE simulation_events (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    trip_id BIGINT UNSIGNED NOT NULL,
    event_type ENUM(
        'trip_started', 'pause', 'resume', 'playback_change',
        'traffic_change', 'weather_change', 'student_stop',
        'incident', 'emergency_stop', 'manual_speed_change',
        'route_deviation', 'road_obstacle', 'route_return'
    ) NOT NULL,
    simulated_time_sec INT UNSIGNED NOT NULL,
    event_data JSON NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_events_trip
        FOREIGN KEY (trip_id) REFERENCES trips(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE anomaly_events (
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
