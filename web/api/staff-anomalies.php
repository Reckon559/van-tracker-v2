<?php
declare(strict_types=1);

require_once dirname(__DIR__) . '/config/app.php';
require_once dirname(__DIR__) . '/config/database.php';
require_once dirname(__DIR__) . '/includes/auth.php';
require_once dirname(__DIR__) . '/includes/trips.php';

require_any_role(['admin', 'driver']);
$tripId = positive_int($_GET['trip_id'] ?? null);
if ($tripId === null) {
    json_result(['error' => 'trip_id is required.'], 400);
}

$pdo = database();
if (find_accessible_trip($pdo, $tripId) === null) {
    json_result(['error' => 'Trip not found or access denied.'], 404);
}

$statement = $pdo->prepare(
    "SELECT id, anomaly_type, classification, isolation_status,
            isolation_score, audience, reason, created_at
     FROM anomaly_events
     WHERE trip_id = :trip_id AND audience <> 'none'
     ORDER BY id DESC
     LIMIT 30"
);
$statement->execute(['trip_id' => $tripId]);
json_result(['events' => $statement->fetchAll()]);
