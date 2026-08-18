<?php
require dirname(__DIR__) . '/web/config/database.php';
$pdo = database();

echo "=== Normalizing all timestamps to present time ===\n";
$r1 = $pdo->exec("UPDATE trips SET created_at = NOW() WHERE created_at > NOW()");
$r2 = $pdo->exec("UPDATE anomaly_events SET created_at = NOW() WHERE created_at > NOW()");
$r3 = $pdo->exec("UPDATE notifications SET created_at = NOW() WHERE created_at > NOW()");
$r4 = $pdo->exec("UPDATE trip_telemetry SET recorded_at = NOW() WHERE recorded_at > NOW()");
$r5 = $pdo->exec("UPDATE trip_stops SET attendance_marked_at = NOW() WHERE attendance_marked_at > NOW()");

echo "Updated rows: trips ($r1), anomaly_events ($r2), notifications ($r3), trip_telemetry ($r4), trip_stops ($r5)\n";
echo "Done!\n";
