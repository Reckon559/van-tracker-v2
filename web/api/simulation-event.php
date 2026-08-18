<?php
declare(strict_types=1);

require_once dirname(__DIR__) . '/config/app.php';
require_once dirname(__DIR__) . '/config/database.php';
require_once dirname(__DIR__) . '/includes/auth.php';
require_once dirname(__DIR__) . '/includes/trips.php';

require_any_role(['admin', 'driver']);
verify_csrf_header();
$payload = read_json_request();
$tripId = positive_int($payload['trip_id'] ?? null);
$eventType = (string) ($payload['event_type'] ?? '');
$allowed = [
    'trip_started', 'pause', 'resume', 'playback_change',
    'emergency_stop', 'manual_speed_change',
    'route_deviation', 'road_obstacle', 'route_return',
];

if ($tripId === null || !in_array($eventType, $allowed, true)) {
    json_result(['error' => 'Invalid trip or event type.'], 400);
}

$pdo = database();
if (find_accessible_trip($pdo, $tripId) === null) {
    json_result(['error' => 'Trip not found or access denied.'], 404);
}

$statement = $pdo->prepare(
    'INSERT INTO simulation_events
        (trip_id, event_type, simulated_time_sec, event_data)
     VALUES
        (:trip_id, :event_type, :simulated_time_sec, :event_data)'
);
$statement->execute([
    'trip_id' => $tripId,
    'event_type' => $eventType,
    'simulated_time_sec' => max(
        0,
        (int) round((float) ($payload['simulated_time_sec'] ?? 0))
    ),
    'event_data' => json_encode(
        is_array($payload['event_data'] ?? null) ? $payload['event_data'] : [],
        JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE
    ),
]);

json_result(['ok' => true], 201);
