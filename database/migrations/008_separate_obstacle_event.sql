USE van_tracker_v2;

ALTER TABLE simulation_events
    MODIFY event_type ENUM(
        'trip_started', 'pause', 'resume', 'playback_change',
        'traffic_change', 'weather_change', 'student_stop',
        'incident', 'emergency_stop', 'manual_speed_change',
        'route_deviation', 'road_obstacle', 'route_return'
    ) NOT NULL;
