<?php
require dirname(__DIR__) . '/web/config/database.php';
$pdo = database();

echo "=== Current Database Time ===\n";
echo "MySQL NOW(): " . $pdo->query("SELECT NOW()")->fetchColumn() . "\n";
echo "PHP date(): " . date('Y-m-d H:i:s') . "\n\n";

echo "=== Anomaly Events in the Future ===\n";
$stmt = $pdo->query("SELECT id, trip_id, anomaly_type, classification, created_at FROM anomaly_events WHERE created_at > NOW() ORDER BY created_at DESC LIMIT 10");
foreach ($stmt->fetchAll() as $row) {
    echo "ID {$row['id']} | Trip #{$row['trip_id']} | {$row['anomaly_type']} | {$row['classification']} | {$row['created_at']}\n";
}

echo "\n=== Notifications in the Future ===\n";
$stmt = $pdo->query("SELECT id, trip_id, type, message, created_at FROM notifications WHERE created_at > NOW() ORDER BY created_at DESC LIMIT 10");
foreach ($stmt->fetchAll() as $row) {
    echo "ID {$row['id']} | Trip #{$row['trip_id']} | {$row['type']} | {$row['message']} | {$row['created_at']}\n";
}

echo "\n=== Trips with Future timestamps ===\n";
$stmt = $pdo->query("SELECT id, trip_type, status, created_at, started_at FROM trips WHERE created_at > NOW() OR started_at > NOW() ORDER BY id DESC LIMIT 10");
foreach ($stmt->fetchAll() as $row) {
    echo "Trip #{$row['id']} | {$row['trip_type']} | {$row['status']} | Created: {$row['created_at']} | Started: {$row['started_at']}\n";
}
