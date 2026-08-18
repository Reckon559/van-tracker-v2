USE van_tracker_v2;

ALTER TABLE trip_stops
    MODIFY stop_type ENUM('student_home', 'school', 'depot') NOT NULL;

ALTER TABLE simulation_events
    MODIFY event_type ENUM(
        'trip_started', 'pause', 'resume', 'playback_change',
        'traffic_change', 'weather_change', 'student_stop',
        'incident', 'emergency_stop', 'manual_speed_change'
    ) NOT NULL;

