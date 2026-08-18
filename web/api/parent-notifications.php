<?php
declare(strict_types=1);

require_once dirname(__DIR__) . '/config/app.php';
require_once dirname(__DIR__) . '/config/database.php';
require_once dirname(__DIR__) . '/includes/auth.php';
require_once dirname(__DIR__) . '/includes/trips.php';

require_role('parent');
$afterId = filter_var($_GET['after_id'] ?? 0, FILTER_VALIDATE_INT);
if ($afterId === false || $afterId < 0) $afterId = 0;

$pdo = database();
$order = $afterId === 0 ? 'DESC' : 'ASC';
$statement = $pdo->prepare(
    'SELECT n.id, n.trip_id, n.type, n.message, n.is_read, n.created_at
     FROM notifications n
     JOIN students notification_student
       ON notification_student.id = n.student_id
      AND notification_student.parent_id = n.parent_id
     LEFT JOIN trips t ON t.id = n.trip_id
     LEFT JOIN trip_stops ts
       ON ts.trip_id = n.trip_id AND ts.student_id = n.student_id
     WHERE n.parent_id = :parent_id
       AND notification_student.parent_id = :verified_parent_id
       AND n.id > :after_id
       AND (n.trip_id IS NULL
            OR t.trip_type = \'morning\'
            OR ts.attendance_status = \'present\')
       AND (
           t.trip_type IS NULL
           OR t.trip_type <> \'afternoon\'
           OR n.type = \'arrived\'
           OR ts.arrived_at IS NULL
           OR n.created_at < ts.arrived_at
       )
     ORDER BY n.id ' . $order . '
     LIMIT 30'
);
$statement->bindValue(':parent_id', (int) $_SESSION['user_id'], PDO::PARAM_INT);
$statement->bindValue(':verified_parent_id', (int) $_SESSION['user_id'], PDO::PARAM_INT);
$statement->bindValue(':after_id', $afterId, PDO::PARAM_INT);
$statement->execute();
$notifications = $statement->fetchAll();
if ($afterId === 0) {
    $notifications = array_reverse($notifications);
}
foreach ($notifications as &$notification) {
    $notification['key'] = 'notification-' . (int) $notification['id'];
}
unset($notification);

$absenceStatement = $pdo->prepare(
    "SELECT ts.id, ts.trip_id, ts.attendance_marked_at,
            s.name AS student_name
     FROM trip_stops ts
     JOIN trips t ON t.id = ts.trip_id
     JOIN students s ON s.id = ts.student_id
     WHERE s.parent_id = :parent_id
       AND t.trip_type = 'afternoon'
       AND ts.attendance_status = 'absent'
       AND ts.attendance_marked_at IS NOT NULL
     ORDER BY ts.attendance_marked_at DESC
     LIMIT 20"
);
$absenceStatement->execute(['parent_id' => (int) $_SESSION['user_id']]);
foreach ($absenceStatement->fetchAll() as $absence) {
    $notifications[] = [
        'id' => 0,
        'key' => 'absence-' . (int) $absence['id'],
        'trip_id' => (int) $absence['trip_id'],
        'type' => 'absence',
        'message' => 'Attendance update: ' . $absence['student_name']
            . ' was marked absent and will not travel on this trip.',
        'is_read' => 0,
        'created_at' => $absence['attendance_marked_at'],
    ];
}

usort($notifications, static function (array $first, array $second): int {
    return strtotime((string) $first['created_at'])
        <=> strtotime((string) $second['created_at']);
});

$notifications = array_slice($notifications, -50);
$recentTripId = $notifications
    ? (int) ($notifications[count($notifications) - 1]['trip_id'] ?? 0)
    : 0;

json_result([
    'notifications' => $notifications,
    'recent_trip_id' => $recentTripId,
]);
