<?php
declare(strict_types=1);

require_once dirname(__DIR__) . '/config/app.php';
require_once dirname(__DIR__) . '/config/database.php';
require_once dirname(__DIR__) . '/includes/auth.php';
require_once dirname(__DIR__) . '/includes/trips.php';

require_role('driver');
$pdo = database();

$driverStatement = $pdo->prepare(
    'SELECT id FROM drivers WHERE user_id = :user_id LIMIT 1'
);
$driverStatement->execute(['user_id' => $_SESSION['user_id']]);
$driverId = (int) ($driverStatement->fetchColumn() ?: 0);
if ($driverId <= 0) {
    json_result(['error' => 'Driver account is not configured.'], 404);
}

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    verify_csrf_header();
    $payload = read_json_request();
    $tripId = positive_int($payload['trip_id'] ?? null);
    $studentId = positive_int($payload['student_id'] ?? null);
    $boarded = filter_var(
        $payload['boarded'] ?? null,
        FILTER_VALIDATE_BOOLEAN,
        FILTER_NULL_ON_FAILURE
    );
    if ($tripId === null || $studentId === null || $boarded === null) {
        json_result(['error' => 'trip_id, student_id and boarded are required.'], 400);
    }

    $tripStatement = $pdo->prepare(
        "SELECT t.id
         FROM trips t
         WHERE t.id = :trip_id
           AND t.driver_id = :driver_id
           AND t.trip_type = 'afternoon'
           AND t.status = 'scheduled'"
    );
    $tripStatement->execute([
        'trip_id' => $tripId,
        'driver_id' => $driverId,
    ]);
    if (!$tripStatement->fetchColumn()) {
        json_result([
            'error' => 'Attendance can only be changed before an afternoon trip leaves school.',
        ], 409);
    }

    $studentStatement = $pdo->prepare(
        'SELECT 1
         FROM trip_stops
         WHERE trip_id = :trip_id AND student_id = :student_id
         LIMIT 1'
    );
    $studentStatement->execute([
        'trip_id' => $tripId,
        'student_id' => $studentId,
    ]);
    if (!$studentStatement->fetchColumn()) {
        json_result(['error' => 'Student is not assigned to this trip.'], 404);
    }

    $update = $pdo->prepare(
        "INSERT INTO trip_attendance (
            trip_id, student_id, status, marked_by_driver_id, marked_at
         ) VALUES (
            :trip_id, :student_id, :status, :driver_id, :marked_at
         )
         ON DUPLICATE KEY UPDATE
            status = VALUES(status),
            marked_by_driver_id = VALUES(marked_by_driver_id),
            marked_at = VALUES(marked_at)"
    );
    $update->execute([
        'trip_id' => $tripId,
        'student_id' => $studentId,
        'status' => $boarded ? 'boarded' : 'pending',
        'driver_id' => $driverId,
        'marked_at' => $boarded ? date('Y-m-d H:i:s') : null,
    ]);
    json_result(['ok' => true, 'status' => $boarded ? 'boarded' : 'pending']);
}

$tripStatement = $pdo->prepare(
    "SELECT t.id, t.status, t.trip_type, r.name AS route_name, v.van_number
     FROM trips t
     JOIN routes r ON r.id = t.route_id
     JOIN vans v ON v.id = t.van_id
     WHERE t.driver_id = :driver_id
       AND t.trip_type = 'afternoon'
       AND t.status IN ('scheduled', 'active', 'paused', 'emergency')
     ORDER BY t.id DESC
     LIMIT 1"
);
$tripStatement->execute(['driver_id' => $driverId]);
$trip = $tripStatement->fetch();
if (!$trip) {
    json_result(['status' => 'idle', 'students' => []]);
}

// Compatibility for trips created before migration 007 was installed.
$seed = $pdo->prepare(
    "INSERT IGNORE INTO trip_attendance (trip_id, student_id)
     SELECT ts.trip_id, ts.student_id
     FROM trip_stops ts
     WHERE ts.trip_id = :trip_id
       AND ts.student_id IS NOT NULL"
);
$seed->execute(['trip_id' => $trip['id']]);

$studentsStatement = $pdo->prepare(
    "SELECT s.id AS student_id, s.name, s.pickup_location,
            ts.stop_order, ta.status, ta.marked_at
     FROM trip_stops ts
     JOIN students s ON s.id = ts.student_id
     JOIN trip_attendance ta
       ON ta.trip_id = ts.trip_id AND ta.student_id = ts.student_id
     WHERE ts.trip_id = :trip_id
     ORDER BY ts.stop_order"
);
$studentsStatement->execute(['trip_id' => $trip['id']]);
$students = $studentsStatement->fetchAll();
$boardedCount = count(array_filter(
    $students,
    static fn(array $student): bool => $student['status'] === 'boarded'
));

json_result([
    'status' => $trip['status'],
    'trip_id' => (int) $trip['id'],
    'route_name' => $trip['route_name'],
    'van_number' => $trip['van_number'],
    'editable' => $trip['status'] === 'scheduled',
    'boarded_count' => $boardedCount,
    'total_count' => count($students),
    'students' => array_map(
        static fn(array $student): array => [
            'student_id' => (int) $student['student_id'],
            'name' => $student['name'],
            'pickup_location' => $student['pickup_location'],
            'stop_order' => (int) $student['stop_order'],
            'status' => $student['status'],
            'marked_at' => $student['marked_at'],
        ],
        $students
    ),
]);
