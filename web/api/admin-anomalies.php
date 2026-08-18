<?php
declare(strict_types=1);

require_once dirname(__DIR__) . '/config/app.php';
require_once dirname(__DIR__) . '/config/database.php';
require_once dirname(__DIR__) . '/includes/auth.php';
require_once dirname(__DIR__) . '/includes/trips.php';

require_role('admin');

$pdo = database();
$statement = $pdo->query(
    "SELECT ae.id, ae.anomaly_type, ae.classification,
            ae.isolation_status, ae.isolation_score, ae.audience,
            ae.reason, ae.created_at, ae.trip_id,
            t.trip_type, v.van_number, r.name AS route_name
     FROM anomaly_events ae
     JOIN trips t ON t.id = ae.trip_id
     JOIN vans v ON v.id = t.van_id
     JOIN routes r ON r.id = t.route_id
     WHERE ae.classification = 'suspicious'
        OR ae.audience <> 'none'
     ORDER BY ae.id DESC
     LIMIT 40"
);
$events = [];
foreach ($statement->fetchAll() as $event) {
    $event['id'] = 'anomaly-' . (int) $event['id'];
    $events[] = $event;
}

$absenceStatement = $pdo->query(
    "SELECT ts.id, ts.trip_id, ts.attendance_marked_at,
            s.name AS student_name, t.trip_type,
            v.van_number, r.name AS route_name
     FROM trip_stops ts
     JOIN trips t ON t.id = ts.trip_id
     JOIN students s ON s.id = ts.student_id
     JOIN vans v ON v.id = t.van_id
     JOIN routes r ON r.id = t.route_id
     WHERE t.trip_type = 'afternoon'
       AND ts.attendance_status = 'absent'
       AND ts.attendance_marked_at IS NOT NULL
     ORDER BY ts.attendance_marked_at DESC
     LIMIT 30"
);
foreach ($absenceStatement->fetchAll() as $absence) {
    $events[] = [
        'id' => 'absence-' . (int) $absence['id'],
        'anomaly_type' => 'absence',
        'classification' => 'monitor',
        'isolation_status' => 'not_applicable',
        'isolation_score' => null,
        'audience' => 'admin',
        'reason' => $absence['student_name']
            . ' was marked absent for this afternoon trip.',
        'created_at' => $absence['attendance_marked_at'],
        'trip_id' => (int) $absence['trip_id'],
        'trip_type' => $absence['trip_type'],
        'van_number' => $absence['van_number'],
        'route_name' => $absence['route_name'],
    ];
}

usort($events, static function (array $first, array $second): int {
    return strtotime((string) $second['created_at'])
        <=> strtotime((string) $first['created_at']);
});

$events = array_slice($events, 0, 50);
json_result([
    'events' => $events,
    'recent_trip_id' => $events ? (int) $events[0]['trip_id'] : 0,
]);
