<?php
declare(strict_types=1);

require_once dirname(__DIR__) . '/config/app.php';
require_once dirname(__DIR__) . '/config/database.php';
require_once dirname(__DIR__) . '/includes/auth.php';
require_once dirname(__DIR__) . '/includes/trips.php';

require_role('driver');
$pdo = database();
$userId = (int) $_SESSION['user_id'];
$events = [];

$absenceStatement = $pdo->prepare(
    "SELECT ts.id, ts.trip_id, ts.attendance_marked_at,
            s.name AS student_name, v.van_number, r.name AS route_name
     FROM trip_stops ts
     JOIN trips t ON t.id = ts.trip_id
     JOIN drivers d ON d.id = t.driver_id
     JOIN students s ON s.id = ts.student_id
     JOIN vans v ON v.id = t.van_id
     JOIN routes r ON r.id = t.route_id
     WHERE d.user_id = :user_id
       AND t.trip_type = 'afternoon'
       AND ts.attendance_status = 'absent'
       AND ts.attendance_marked_at IS NOT NULL
     ORDER BY ts.attendance_marked_at DESC
     LIMIT 30"
);
$absenceStatement->execute(['user_id' => $userId]);
foreach ($absenceStatement->fetchAll() as $row) {
    $events[] = [
        'id' => 'absence-' . (int) $row['id'],
        'type' => 'absence',
        'trip_id' => (int) $row['trip_id'],
        'van_number' => $row['van_number'],
        'route_name' => $row['route_name'],
        'message' => $row['student_name']
            . ' was marked absent. ETA and arrival alerts are disabled.',
        'created_at' => $row['attendance_marked_at'],
    ];
}

$overspeedStatement = $pdo->prepare(
    "SELECT ae.id, ae.trip_id, ae.reason, ae.created_at,
            v.van_number, r.name AS route_name
     FROM anomaly_events ae
     JOIN trips t ON t.id = ae.trip_id
     JOIN drivers d ON d.id = t.driver_id
     JOIN vans v ON v.id = t.van_id
     JOIN routes r ON r.id = t.route_id
     WHERE d.user_id = :user_id
       AND ae.anomaly_type = 'overspeed'
       AND ae.classification = 'suspicious'
     ORDER BY ae.id DESC
     LIMIT 30"
);
$overspeedStatement->execute(['user_id' => $userId]);
foreach ($overspeedStatement->fetchAll() as $row) {
    $events[] = [
        'id' => 'overspeed-' . (int) $row['id'],
        'type' => 'overspeed',
        'trip_id' => (int) $row['trip_id'],
        'van_number' => $row['van_number'],
        'route_name' => $row['route_name'],
        'message' => $row['reason'],
        'created_at' => $row['created_at'],
    ];
}

usort($events, static function (array $first, array $second): int {
    return strtotime((string) $second['created_at'])
        <=> strtotime((string) $first['created_at']);
});

$events = array_slice($events, 0, 30);
json_result([
    'events' => $events,
    'recent_trip_id' => $events ? (int) $events[0]['trip_id'] : 0,
]);
