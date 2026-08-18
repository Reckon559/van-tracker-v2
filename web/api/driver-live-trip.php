<?php
declare(strict_types=1);

require_once dirname(__DIR__) . '/config/app.php';
require_once dirname(__DIR__) . '/config/database.php';
require_once dirname(__DIR__) . '/includes/auth.php';
require_once dirname(__DIR__) . '/includes/trips.php';

require_role('driver');
$pdo = database();
$statement = $pdo->prepare(
    "SELECT t.id AS trip_id, t.status, t.trip_type,
            t.current_lat, t.current_lng, t.physical_speed_kmh,
            t.playback_multiplier, t.simulated_elapsed_sec,
            t.total_distance_m, t.distance_travelled_m,
            t.reached_stop_count, t.heading_deg,
            t.predicted_eta_sec, t.predicted_eta_lower_sec,
            t.predicted_eta_upper_sec, t.eta_model_version,
            t.scenario_traffic_level, t.scenario_weather,
            t.scenario_school_period, t.scenario_hour_of_day,
            t.scenario_day_of_week, t.baseline_duration_sec,
            r.name AS route_name, v.van_number
     FROM trips t
     JOIN drivers d ON d.id = t.driver_id
     JOIN routes r ON r.id = t.route_id
     JOIN vans v ON v.id = t.van_id
     WHERE d.user_id = :user_id
       AND t.status IN ('scheduled', 'active', 'paused', 'emergency')
     ORDER BY t.id DESC
     LIMIT 1"
);
$statement->execute(['user_id' => $_SESSION['user_id']]);
$trip = $statement->fetch();

if (!$trip) {
    json_result(['status' => 'idle']);
}

$nextStopStatement = $pdo->prepare(
    "SELECT stop_name
     FROM trip_stops
     WHERE trip_id = :trip_id
       AND status = 'pending'
       AND (:trip_type = 'morning'
            OR student_id IS NULL OR attendance_status = 'present')
     ORDER BY stop_order
     LIMIT 1"
);
$nextStopStatement->execute([
    'trip_id' => $trip['trip_id'],
    'trip_type' => $trip['trip_type'],
]);
$nextStop = $nextStopStatement->fetchColumn();

$total = max(0, (float) $trip['total_distance_m']);
$travelled = max(0, (float) $trip['distance_travelled_m']);
$remaining = max(0, $total - $travelled);
$speedMps = max(0, (float) $trip['physical_speed_kmh']) / 3.6;
$eta = $speedMps > 0 && $trip['status'] === 'active'
    ? $remaining / $speedMps
    : null;
$freeFlowEta = $trip['baseline_duration_sec'] !== null && $total > 0
    ? (float) $trip['baseline_duration_sec'] * $remaining / $total
    : ($eta ?? 0);
$scenarioEta = $freeFlowEta * scenario_eta_multiplier(
    (string) $trip['scenario_traffic_level'],
    (string) $trip['scenario_weather'],
    (string) $trip['scenario_school_period'],
    (int) $trip['scenario_hour_of_day'],
    (int) $trip['scenario_day_of_week']
);

json_result([
    'status' => $trip['status'],
    'trip_id' => (int) $trip['trip_id'],
    'trip_type' => $trip['trip_type'],
    'route_name' => $trip['route_name'],
    'van_number' => $trip['van_number'],
    'latitude' => (float) $trip['current_lat'],
    'longitude' => (float) $trip['current_lng'],
    'current_speed_kmh' => $trip['status'] === 'active'
        ? (float) $trip['physical_speed_kmh']
        : 0.0,
    'heading_deg' => (float) $trip['heading_deg'],
    'total_distance_m' => $total,
    'distance_travelled_m' => $travelled,
    'route_progress' => $total > 0 ? min(1, $travelled / $total) : 0,
    'route_remaining_m' => $remaining,
    'route_end_eta_sec' => round($scenarioEta, 2),
    'rf_eta_sec' => $trip['predicted_eta_sec'] !== null
        ? (float) $trip['predicted_eta_sec'] : null,
    'rf_eta_lower_sec' => $trip['predicted_eta_lower_sec'] !== null
        ? (float) $trip['predicted_eta_lower_sec'] : null,
    'rf_eta_upper_sec' => $trip['predicted_eta_upper_sec'] !== null
        ? (float) $trip['predicted_eta_upper_sec'] : null,
    'eta_model_version' => $trip['eta_model_version'],
    'traffic_level' => $trip['scenario_traffic_level'],
    'weather' => $trip['scenario_weather'],
    'school_period' => $trip['scenario_school_period'],
    'next_stop' => $nextStop ?: 'Final destination',
]);
