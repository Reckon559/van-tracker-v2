<?php
require dirname(__DIR__) . '/web/config/database.php';
$pdo = database();

echo "=== DATABASE INTEGRITY AUDIT ===\n";
$tables = [
    'users', 'vans', 'drivers', 'routes', 'students', 'route_students',
    'trips', 'trip_stops', 'trip_attendance', 'trip_telemetry',
    'anomaly_events', 'simulation_events', 'notifications', 'eta_predictions'
];

foreach ($tables as $table) {
    $count = $pdo->query("SELECT COUNT(*) FROM `{$table}`")->fetchColumn();
    echo sprintf("%-22s : %6d rows\n", $table, $count);
}

echo "\n=== FOREIGN KEY & RELATIONSHIP INTEGRITY ===\n";

// 1. Orphaned drivers
$orphanedDrivers = $pdo->query("SELECT COUNT(*) FROM drivers d LEFT JOIN users u ON u.id = d.user_id WHERE u.id IS NULL")->fetchColumn();
echo "Orphaned drivers (missing user): $orphanedDrivers\n";

// 2. Orphaned students
$orphanedStudents = $pdo->query("SELECT COUNT(*) FROM students s LEFT JOIN users u ON u.id = s.parent_id WHERE u.id IS NULL")->fetchColumn();
echo "Orphaned students (missing parent): $orphanedStudents\n";

// 3. Orphaned route_students
$orphanedRouteStudents = $pdo->query("SELECT COUNT(*) FROM route_students rs LEFT JOIN routes r ON r.id = rs.route_id LEFT JOIN students s ON s.id = rs.student_id WHERE r.id IS NULL OR s.id IS NULL")->fetchColumn();
echo "Orphaned route_students: $orphanedRouteStudents\n";

// 4. Orphaned trips
$orphanedTrips = $pdo->query("SELECT COUNT(*) FROM trips t LEFT JOIN routes r ON r.id = t.route_id LEFT JOIN vans v ON v.id = t.van_id LEFT JOIN drivers d ON d.id = t.driver_id WHERE r.id IS NULL OR v.id IS NULL OR d.id IS NULL")->fetchColumn();
echo "Orphaned trips: $orphanedTrips\n";

// 5. Orphaned trip_stops
$orphanedTripStops = $pdo->query("SELECT COUNT(*) FROM trip_stops ts LEFT JOIN trips t ON t.id = ts.trip_id WHERE t.id IS NULL")->fetchColumn();
echo "Orphaned trip_stops: $orphanedTripStops\n";

// 6. Orphaned notifications
$orphanedNotifications = $pdo->query("SELECT COUNT(*) FROM notifications n LEFT JOIN users u ON u.id = n.parent_id LEFT JOIN students s ON s.id = n.student_id WHERE (n.parent_id IS NOT NULL AND u.id IS NULL) OR (n.student_id IS NOT NULL AND s.id IS NULL)")->fetchColumn();
echo "Orphaned notifications: $orphanedNotifications\n";

// 7. Check future timestamps
$futureCount = $pdo->query("SELECT (SELECT COUNT(*) FROM anomaly_events WHERE created_at > NOW()) + (SELECT COUNT(*) FROM notifications WHERE created_at > NOW()) + (SELECT COUNT(*) FROM trips WHERE created_at > NOW())")->fetchColumn();
echo "Records with future timestamps: $futureCount\n";

echo "\nDatabase integrity audit complete!\n";
