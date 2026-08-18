<?php
declare(strict_types=1);

require_once dirname(__DIR__) . '/config/app.php';
require_once dirname(__DIR__) . '/config/database.php';
require_once dirname(__DIR__) . '/includes/auth.php';
require_once dirname(__DIR__) . '/includes/trips.php';

require_role('parent');
header('Cache-Control: no-store, no-cache, must-revalidate');
$pdo = database();
$statement = $pdo->prepare(
    "SELECT t.id AS trip_id, t.status, t.trip_type,
            t.current_lat, t.current_lng, t.physical_speed_kmh,
            t.playback_multiplier, t.simulated_elapsed_sec,
            t.total_distance_m, t.distance_travelled_m,
            t.reached_stop_count, t.heading_deg,
            t.scenario_traffic_level, t.scenario_weather,
            t.scenario_school_period, t.scenario_hour_of_day,
            t.scenario_day_of_week, t.route_road_type,
            t.baseline_duration_sec, t.eta_model_version,
            r.name AS route_name, r.school_name, r.school_lat, r.school_lng,
            v.van_number, v.speed_limit_kmh,
            s.id AS student_id, s.name AS student_name,
            s.pickup_location, s.pickup_lat, s.pickup_lng,
            ts.stop_order, ts.status AS student_stop_status,
            ts.route_distance_m, ts.attendance_status,
            (SELECT COUNT(*)
             FROM trip_stops active_ts
             WHERE active_ts.trip_id = ts.trip_id
               AND active_ts.stop_order <= ts.stop_order
               AND (t.trip_type = 'morning'
                    OR active_ts.student_id IS NULL
                    OR active_ts.attendance_status = 'present')) AS active_stop_number
            ,(SELECT COUNT(*)
              FROM trip_stops active_all
              WHERE active_all.trip_id = ts.trip_id) AS active_stop_count
     FROM students s
     JOIN trips t ON t.van_id = s.van_id
     JOIN trip_stops ts
       ON ts.trip_id = t.id AND ts.student_id = s.id
     JOIN routes r ON r.id = t.route_id
     JOIN vans v ON v.id = t.van_id
     WHERE s.parent_id = :parent_id
       AND s.active = 1
       AND t.status <> 'cancelled'
     ORDER BY t.id DESC
     LIMIT 1"
);
$statement->execute(['parent_id' => $_SESSION['user_id']]);
$trip = $statement->fetch();

if (!$trip) {
    json_result(['status' => 'idle']);
}

$total = max(0, (float) $trip['total_distance_m']);
$travelled = max(0, (float) $trip['distance_travelled_m']);
$homeRouteDistance = $trip['route_distance_m'] !== null
    ? max(0, (float) $trip['route_distance_m'])
    : null;
$isMorning = $trip['trip_type'] === 'morning';
$storedAttendanceStatus = (string) $trip['attendance_status'];
$attendanceStatus = $isMorning ? 'not_required' : $storedAttendanceStatus;
$studentEligible = $isMorning || $storedAttendanceStatus === 'present';
$trackingDistance = !$isMorning && $storedAttendanceStatus === 'unmarked'
    ? null
    : ($studentEligible && $isMorning
        ? ($total > 0 ? $total : null)
        : $homeRouteDistance);
$trackingComplete = $trackingDistance !== null
    && $travelled + 1.0 >= $trackingDistance;
$studentReached = $studentEligible && (
    ($isMorning && $trip['status'] === 'completed')
    || (!$isMorning && $trackingComplete)
);
if ($studentEligible && !$isMorning && !$studentReached && $trackingDistance !== null) {
    // Route distance is the authoritative completion check. This prevents an
    // old "arrived" flag from completing the parent view after the in-memory
    // Python simulation has been restarted from the beginning.
    $studentReached = $travelled + 1.0 >= $trackingDistance;
} elseif ($studentEligible && !$isMorning && !$studentReached) {
    // Compatibility fallback for trips created before route distances existed.
    $studentReached = $trip['student_stop_status'] === 'arrived'
        || (int) $trip['reached_stop_count'] >= (int) $trip['stop_order'];
}
$remaining = $trackingDistance !== null
    ? max(0, $trackingDistance - $travelled)
    : null;
$speedMps = max(0, (float) $trip['physical_speed_kmh']) / 3.6;
$eta = !$studentReached && $remaining !== null
    && $speedMps > 0 && $trip['status'] === 'active'
    ? $remaining / $speedMps
    : null;
$parentStatus = !$studentEligible
    ? ($storedAttendanceStatus === 'absent'
        ? ($trackingComplete ? 'tracking_complete' : 'absent_tracking')
        : 'attendance_pending')
    : ($studentReached ? 'completed' : $trip['status']);
$visibleLatitude = $studentReached || $trackingComplete
    ? (float) ($isMorning && $studentEligible
        ? $trip['school_lat'] : $trip['pickup_lat'])
    : (float) $trip['current_lat'];
$visibleLongitude = $studentReached || $trackingComplete
    ? (float) ($isMorning && $studentEligible
        ? $trip['school_lng'] : $trip['pickup_lng'])
    : (float) $trip['current_lng'];
$studentProgress = $trackingDistance !== null && $trackingDistance > 0
    ? min(1, $travelled / $trackingDistance)
    : 0;
$baselineRemaining = $trip['baseline_duration_sec'] !== null
    && $total > 0 && $remaining !== null
    ? max(0, (float) $trip['baseline_duration_sec'] * $remaining / $total)
    : ($eta ?? 0);
$scenarioBaselineRemaining = $baselineRemaining * scenario_eta_multiplier(
    (string) $trip['scenario_traffic_level'],
    (string) $trip['scenario_weather'],
    (string) $trip['scenario_school_period'],
    (int) $trip['scenario_hour_of_day'],
    (int) $trip['scenario_day_of_week']
);
$stopsRemaining = max(
    0,
    ($isMorning
        ? (int) $trip['active_stop_count']
        : (int) $trip['stop_order']) - (int) $trip['reached_stop_count']
);

json_result([
    'status' => $parentStatus,
    'trip_id' => (int) $trip['trip_id'],
    'trip_type' => $trip['trip_type'],
    'route_name' => $trip['route_name'],
    'van_number' => $trip['van_number'],
    'student_id' => (int) $trip['student_id'],
    'student_stop_order' => (int) $trip['stop_order'],
    'active_stop_number' => (int) $trip['active_stop_number'],
    'tracking_stop_number' => $isMorning
        && $studentEligible
        ? (int) $trip['active_stop_count'] : (int) $trip['stop_order'],
    'student_name' => $trip['student_name'],
    'attendance_status' => $attendanceStatus,
    'attendance_required' => !$isMorning,
    'eta_enabled' => $studentEligible,
    'pickup_location' => $trip['pickup_location'],
    'tracking_destination' => $isMorning
        && $studentEligible ? $trip['school_name'] : $trip['pickup_location'],
    'latitude' => $visibleLatitude,
    'longitude' => $visibleLongitude,
    'home_latitude' => (float) $trip['pickup_lat'],
    'home_longitude' => (float) $trip['pickup_lng'],
    'physical_speed_kmh' => (float) $trip['physical_speed_kmh'],
    'current_speed_kmh' => !$trackingComplete && !$studentReached
        && $trip['status'] === 'active'
        ? (float) $trip['physical_speed_kmh']
        : 0.0,
    'heading_deg' => (float) $trip['heading_deg'],
    'playback_multiplier' => (float) $trip['playback_multiplier'],
    'simulated_elapsed_sec' => (int) $trip['simulated_elapsed_sec'],
    'total_distance_m' => $total,
    'distance_travelled_m' => $studentReached || $trackingComplete
        ? ($trackingDistance ?? $travelled)
        : $travelled,
    'student_route_distance_m' => $trackingDistance,
    'route_progress' => $studentReached || $trackingComplete ? 1 : $studentProgress,
    'route_remaining_m' => $studentReached || $trackingComplete ? 0 : $remaining,
    'route_end_eta_sec' => $studentReached || $trackingComplete
        ? 0
        : round($scenarioBaselineRemaining, 2),
    'student_eta_sec' => !$studentEligible
        ? null : ($studentReached ? 0 : round($scenarioBaselineRemaining, 2)),
    'student_completed' => $studentReached,
    'tracking_complete' => $trackingComplete,
    'baseline_remaining_sec' => $studentReached ? 0 : round($baselineRemaining, 2),
    'scenario_baseline_remaining_sec' => $studentReached
        ? 0 : round($scenarioBaselineRemaining, 2),
    'speed_limit_kmh' => (float) $trip['speed_limit_kmh'],
    'stops_remaining' => $studentReached ? 0 : $stopsRemaining,
    'road_type' => $trip['route_road_type'] ?: 'unclassified',
    'traffic_level' => $trip['scenario_traffic_level'],
    'weather' => $trip['scenario_weather'],
    'school_period' => $trip['scenario_school_period'],
    'hour_of_day' => (int) $trip['scenario_hour_of_day'],
    'day_of_week' => (int) $trip['scenario_day_of_week'],
    'eta_model_version' => $trip['eta_model_version'],
]);
