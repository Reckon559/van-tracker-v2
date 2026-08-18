USE van_tracker_v2;

ALTER TABLE trip_stops
    ADD COLUMN attendance_status ENUM('unmarked', 'present', 'absent')
        NOT NULL DEFAULT 'unmarked' AFTER stop_type,
    ADD COLUMN attendance_marked_at DATETIME NULL AFTER attendance_status,
    ADD COLUMN attendance_marked_by BIGINT UNSIGNED NULL AFTER attendance_marked_at,
    ADD INDEX idx_trip_stops_attendance (trip_id, attendance_status),
    ADD CONSTRAINT fk_trip_stops_attendance_user
        FOREIGN KEY (attendance_marked_by) REFERENCES users(id) ON DELETE SET NULL;

-- Preserve already-running historical trips. New scheduled trips remain
-- unmarked and require the driver to take attendance before Start is enabled.
UPDATE trip_stops ts
JOIN trips t ON t.id = ts.trip_id
SET ts.attendance_status = 'present',
    ts.attendance_marked_at = COALESCE(t.started_at, t.created_at)
WHERE ts.student_id IS NOT NULL
  AND t.status <> 'scheduled';
