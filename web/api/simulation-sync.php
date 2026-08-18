<?php
declare(strict_types=1);

require_once dirname(__DIR__) . '/config/app.php';
require_once dirname(__DIR__) . '/config/database.php';
require_once dirname(__DIR__) . '/includes/auth.php';
require_once dirname(__DIR__) . '/includes/trips.php';

require_role('driver');
verify_csrf_header();
$payload = read_json_request();
$tripId = positive_int($payload['trip_id'] ?? null);
$state = $payload['state'] ?? null;
$samples = $payload['samples'] ?? [];
$legEndDistances = $payload['leg_end_distances_m'] ?? [];
$stopOrders = $payload['stop_orders'] ?? [];

if ($tripId === null || !is_array($state) || !is_array($samples)
    || !is_array($legEndDistances) || !is_array($stopOrders)) {
    json_result([
        'error' => 'trip_id, state, samples, leg_end_distances_m and stop_orders are required.',
    ], 400);
}
if (count($legEndDistances) !== count($stopOrders)) {
    json_result(['error' => 'Each routed leg must map to one trip stop.'], 400);
}
$mappedStopOrders = [];
foreach ($stopOrders as $stopOrder) {
    $validated = filter_var($stopOrder, FILTER_VALIDATE_INT, [
        'options' => ['min_range' => 1],
    ]);
    if ($validated === false || in_array((int) $validated, $mappedStopOrders, true)) {
        json_result(['error' => 'stop_orders must contain unique positive integers.'], 400);
    }
    $mappedStopOrders[] = (int) $validated;
}

$pdo = database();
$trip = find_accessible_trip($pdo, $tripId);
if ($trip === null) {
    json_result(['error' => 'Trip not found or access denied.'], 404);
}
$tripType = (string) $trip['trip_type'];

$statusMap = [
    'ready' => 'scheduled',
    'active' => 'active',
    'paused' => 'paused',
    'emergency' => 'emergency',
    'completed' => 'completed',
];
$simulationStatus = (string) ($state['status'] ?? '');
if (!isset($statusMap[$simulationStatus])) {
    json_result(['error' => 'Invalid simulation status.'], 400);
}
$databaseStatus = $statusMap[$simulationStatus];
if ($tripType === 'afternoon' && $databaseStatus !== 'scheduled') {
    $attendanceCheck = $pdo->prepare(
        "SELECT COUNT(*) FROM trip_stops
         WHERE trip_id = :trip_id
           AND student_id IS NOT NULL
           AND attendance_status = 'unmarked'"
    );
    $attendanceCheck->execute(['trip_id' => $tripId]);
    if ((int) $attendanceCheck->fetchColumn() > 0) {
        json_result(['error' => 'Complete attendance before starting this trip.'], 409);
    }
}
$latitude = valid_coordinate($state['latitude'] ?? null, -90, 90);
$longitude = valid_coordinate($state['longitude'] ?? null, -180, 180);
if ($latitude === null || $longitude === null) {
    json_result(['error' => 'Simulation returned invalid coordinates.'], 400);
}

$simulatedElapsed = max(0, (int) round((float) ($state['simulated_elapsed_sec'] ?? 0)));
$physicalSpeed = max(0, (float) ($state['physical_speed_kmh'] ?? 0));
$playback = (float) ($state['playback_multiplier'] ?? 1);
$totalDistance = max(0, (float) ($state['total_distance_m'] ?? 0));
$travelledDistance = max(0, (float) ($state['distance_travelled_m'] ?? 0));
$reachedStopCount = max(0, (int) ($state['reached_stop_count'] ?? 0));
$heading = fmod((float) ($state['heading_deg'] ?? 0), 360.0);
if ($heading < 0) $heading += 360.0;
$baselineDuration = isset($state['osm_baseline_duration_sec'])
    ? max(0, (float) $state['osm_baseline_duration_sec'])
    : null;
$predictedEta = isset($state['rf_eta_sec'])
    ? max(0, (float) $state['rf_eta_sec'])
    : null;
$predictedLower = isset($state['rf_eta_lower_sec'])
    ? max(0, (float) $state['rf_eta_lower_sec'])
    : null;
$predictedUpper = isset($state['rf_eta_upper_sec'])
    ? max(0, (float) $state['rf_eta_upper_sec'])
    : null;
$modelVersion = isset($state['eta_model_version'])
    ? substr((string) $state['eta_model_version'], 0, 80)
    : null;
$trafficLevel = in_array(($state['traffic_level'] ?? ''), ['low', 'medium', 'high'], true)
    ? (string) $state['traffic_level'] : 'medium';
$weather = in_array(($state['weather'] ?? ''), ['clear', 'rain', 'heavy_rain', 'fog'], true)
    ? (string) $state['weather'] : 'clear';
$roadType = preg_replace('/[^a-z_]/', '', strtolower((string) ($state['road_type'] ?? 'unclassified')));
$hourOfDay = min(23, max(0, (int) ($state['hour_of_day'] ?? 8)));
$dayOfWeek = min(6, max(0, (int) ($state['day_of_week'] ?? 0)));
$anomaly = is_array($state['anomaly'] ?? null) ? $state['anomaly'] : [];
$isolation = is_array($anomaly['isolation_forest'] ?? null)
    ? $anomaly['isolation_forest'] : [];
$decisionLayer = is_array($anomaly['decision_layer'] ?? null)
    ? $anomaly['decision_layer'] : [];
$decisions = is_array($decisionLayer['decisions'] ?? null)
    ? $decisionLayer['decisions'] : [];
$isolationStatus = substr((string) ($isolation['status'] ?? 'unavailable'), 0, 20);
$isolationScore = is_numeric($isolation['score'] ?? null)
    ? (float) $isolation['score'] : null;
$stopEventId = max(0, (int) ($state['stop_event_id'] ?? 0));
$routeDeviationEventId = max(
    0,
    (int) ($state['route_deviation_event_id'] ?? 0)
);
$emergencyEventId = max(0, (int) ($state['emergency_event_id'] ?? 0));
$overspeedEventId = max(0, (int) ($state['overspeed_event_id'] ?? 0));
$stopStartedAt = is_array($state['stop_location'] ?? null)
    ? max(0, (int) round((float) ($state['stop_location']['simulated_time_sec'] ?? 0)))
    : 0;
$newAnomalyEvents = 0;

$pdo->beginTransaction();
try {
    $update = $pdo->prepare(
        'UPDATE trips
         SET status = :status,
             started_at = CASE
                 WHEN :start_trip = 1 AND started_at IS NULL THEN NOW()
                 ELSE started_at
             END,
             completed_at = CASE
                 WHEN :complete_trip = 1 AND completed_at IS NULL THEN NOW()
                 ELSE completed_at
             END,
             simulated_elapsed_sec = :simulated_elapsed_sec,
             current_lat = :current_lat,
             current_lng = :current_lng,
             physical_speed_kmh = :physical_speed_kmh,
             playback_multiplier = :playback_multiplier,
             total_distance_m = :total_distance_m,
             distance_travelled_m = :distance_travelled_m,
             reached_stop_count = :reached_stop_count,
             heading_deg = :heading_deg,
             baseline_duration_sec = :baseline_duration_sec,
             predicted_eta_sec = :predicted_eta_sec,
             predicted_eta_lower_sec = :predicted_eta_lower_sec,
             predicted_eta_upper_sec = :predicted_eta_upper_sec,
             eta_model_version = :eta_model_version,
             route_road_type = :route_road_type
         WHERE id = :trip_id'
    );
    $update->execute([
        'status' => $databaseStatus,
        'start_trip' => in_array($databaseStatus, ['active', 'paused', 'emergency', 'completed'], true) ? 1 : 0,
        'complete_trip' => $databaseStatus === 'completed' ? 1 : 0,
        'simulated_elapsed_sec' => $simulatedElapsed,
        'current_lat' => $latitude,
        'current_lng' => $longitude,
        'physical_speed_kmh' => $physicalSpeed,
        'playback_multiplier' => $playback,
        'total_distance_m' => $totalDistance,
        'distance_travelled_m' => $travelledDistance,
        'reached_stop_count' => $reachedStopCount,
        'heading_deg' => $heading,
        'baseline_duration_sec' => $baselineDuration,
        'predicted_eta_sec' => $predictedEta,
        'predicted_eta_lower_sec' => $predictedLower,
        'predicted_eta_upper_sec' => $predictedUpper,
        'eta_model_version' => $modelVersion,
        'route_road_type' => $roadType ?: 'unclassified',
        'trip_id' => $tripId,
    ]);

    $distanceUpdate = $pdo->prepare(
        'UPDATE trip_stops
         SET route_distance_m = :route_distance_m
         WHERE trip_id = :trip_id AND stop_order = :stop_order'
    );
    foreach (array_slice($legEndDistances, 0, 500) as $index => $distance) {
        if (!is_numeric($distance)) continue;
        $distanceUpdate->execute([
            'route_distance_m' => max(0, (float) $distance),
            'trip_id' => $tripId,
            'stop_order' => $mappedStopOrders[$index],
        ]);
    }

    // Morning pickup routes include every assigned home without attendance.
    // Afternoon routes retain attendance-based eligibility.
    $attendanceEligibility = $tripType === 'morning'
        ? ''
        : "AND (student_id IS NULL OR attendance_status = 'present')";
    $resetMappedStop = $pdo->prepare(
        "UPDATE trip_stops
         SET status = 'pending',
             arrived_at = NULL
         WHERE trip_id = :trip_id
           AND stop_order = :stop_order
           {$attendanceEligibility}"
    );
    $arriveMappedStop = $pdo->prepare(
        "UPDATE trip_stops
         SET status = 'arrived',
             arrived_at = COALESCE(arrived_at, NOW())
         WHERE trip_id = :trip_id
           AND stop_order = :stop_order
           {$attendanceEligibility}"
    );
    foreach ($mappedStopOrders as $index => $mappedStopOrder) {
        $statement = $index < $reachedStopCount
            ? $arriveMappedStop : $resetMappedStop;
        $statement->execute([
            'trip_id' => $tripId,
            'stop_order' => $mappedStopOrder,
        ]);
    }

    $insertLifecycleNotification = $pdo->prepare(
        'INSERT IGNORE INTO notifications (
            parent_id, student_id, trip_id, type, message, dedup_key
         )
         SELECT s.parent_id, s.id, :trip_id, :notification_type,
                CONCAT(:message_prefix, s.name, :message_suffix),
                CONCAT(:dedup_prefix, s.id)
         FROM trip_stops ts
         JOIN students s ON s.id = ts.student_id
         WHERE ts.trip_id = :source_trip_id
           AND (:source_trip_type = \'morning\'
                OR ts.attendance_status = \'present\')
           AND s.parent_id IS NOT NULL
           AND (:arrived_only = 0 OR ts.status = \'arrived\')'
    );

    if ($tripType === 'afternoon' && $databaseStatus !== 'scheduled') {
        $insertLifecycleNotification->execute([
            'trip_id' => $tripId,
            'notification_type' => 'trip_started',
            'message_prefix' => 'School departure: ',
            'message_suffix' => ' has left school in the van.',
            'dedup_prefix' => 'school-departure:' . $tripId . ':',
            'source_trip_id' => $tripId,
            'source_trip_type' => $tripType,
            'arrived_only' => 0,
        ]);
    }

    if ($tripType === 'afternoon' && $reachedStopCount > 0) {
        $insertHomeArrival = $pdo->prepare(
            "INSERT IGNORE INTO notifications (
                parent_id, student_id, trip_id, type, message, dedup_key
             )
             SELECT s.parent_id, s.id, :trip_id, 'arrived',
                    CONCAT('Home arrival: ', s.name, ' has reached home.'),
                    CONCAT('home-arrival:', :trip_id_for_key, ':', s.id)
             FROM trip_stops ts
             JOIN students s ON s.id = ts.student_id
             WHERE ts.trip_id = :source_trip_id
               AND ts.stop_type = 'student_home'
               AND ts.attendance_status = 'present'
               AND ts.status = 'arrived'
               AND s.parent_id IS NOT NULL"
        );
        $insertHomeArrival->execute([
            'trip_id' => $tripId,
            'trip_id_for_key' => $tripId,
            'source_trip_id' => $tripId,
        ]);
    }

    if ($tripType === 'morning' && $databaseStatus === 'completed') {
        $insertLifecycleNotification->execute([
            'trip_id' => $tripId,
            'notification_type' => 'trip_completed',
            'message_prefix' => 'School arrival: ',
            'message_suffix' => ' has arrived at school.',
            'dedup_prefix' => 'school-arrival:' . $tripId . ':',
            'source_trip_id' => $tripId,
            'source_trip_type' => $tripType,
            'arrived_only' => 0,
        ]);
    }

    $insert = $pdo->prepare(
        'INSERT IGNORE INTO trip_telemetry (
            trip_id, sample_index, recorded_at, simulated_time_sec,
            latitude, longitude, current_speed_kmh, speed_limit_kmh,
            road_type, segment_length_m, segment_base_time_sec,
            traffic_level, traffic_multiplier, weather, weather_multiplier,
            stop_delay_sec, incident_delay_sec, distance_remaining_m,
            route_progress, hour_of_day, day_of_week,
            predicted_remaining_sec
         ) VALUES (
            :trip_id, :sample_index, NOW(), :simulated_time_sec,
            :latitude, :longitude, :current_speed_kmh, :speed_limit_kmh,
            :road_type, :segment_length_m, :segment_base_time_sec,
            :traffic_level, :traffic_multiplier, :weather, :weather_multiplier,
            :stop_delay_sec, :incident_delay_sec, :distance_remaining_m,
            :route_progress, :hour_of_day, :day_of_week,
            :predicted_remaining_sec
         )'
    );
    foreach (array_slice($samples, 0, 500) as $sample) {
        if (!is_array($sample)) continue;
        $sampleIndex = filter_var($sample['sample_index'] ?? null, FILTER_VALIDATE_INT);
        $sampleLat = valid_coordinate($sample['latitude'] ?? null, -90, 90);
        $sampleLng = valid_coordinate($sample['longitude'] ?? null, -180, 180);
        if ($sampleIndex === false || $sampleIndex < 0
            || $sampleLat === null || $sampleLng === null) {
            continue;
        }
        $sampleSpeed = max(0, (float) ($sample['current_speed_kmh'] ?? 0));
        $insert->execute([
            'trip_id' => $tripId,
            'sample_index' => $sampleIndex,
            'simulated_time_sec' => max(0, (int) round((float) ($sample['simulated_time_sec'] ?? 0))),
            'latitude' => $sampleLat,
            'longitude' => $sampleLng,
            'current_speed_kmh' => $sampleSpeed,
            'speed_limit_kmh' => max(1, (float) ($sample['speed_limit_kmh'] ?? 40)),
            'road_type' => $roadType ?: 'unclassified',
            'segment_length_m' => round(($sampleSpeed / 3.6) * 5, 2),
            'segment_base_time_sec' => 5,
            'traffic_level' => $trafficLevel,
            'traffic_multiplier' => ['low' => 1.05, 'medium' => 1.45, 'high' => 2.1][$trafficLevel],
            'weather' => $weather,
            'weather_multiplier' => ['clear' => 1.0, 'rain' => 1.16, 'heavy_rain' => 1.4, 'fog' => 1.25][$weather],
            'stop_delay_sec' => 0,
            'incident_delay_sec' => 0,
            'distance_remaining_m' => max(0, (float) ($sample['distance_remaining_m'] ?? 0)),
            'route_progress' => min(1, max(0, (float) ($sample['route_progress'] ?? 0))),
            'hour_of_day' => $hourOfDay,
            'day_of_week' => $dayOfWeek,
            'predicted_remaining_sec' => $predictedEta,
        ]);
    }

    $allowedAnomalyTypes = [
        'route_deviation', 'long_stop', 'emergency_stop', 'overspeed',
    ];
    $allowedClassifications = ['normal', 'monitor', 'suspicious'];
    $allowedAudiences = ['none', 'staff', 'parent'];
    $insertAnomaly = $pdo->prepare(
        'INSERT IGNORE INTO anomaly_events (
            trip_id, anomaly_type, classification, isolation_status,
            isolation_score, audience, reason, decision_data, dedup_key
         ) VALUES (
            :trip_id, :anomaly_type, :classification, :isolation_status,
            :isolation_score, :audience, :reason, :decision_data, :dedup_key
         )'
    );
    $insertParentNotification = $pdo->prepare(
        'INSERT IGNORE INTO notifications (
            parent_id, student_id, trip_id, type, message, dedup_key
         )
         SELECT s.parent_id, s.id, :trip_id, :notification_type,
                :message, CONCAT(:dedup_prefix, s.id)
         FROM trip_stops ts
         JOIN students s ON s.id = ts.student_id
         WHERE ts.trip_id = :source_trip_id
           AND (:eligibility_trip_type = \'morning\'
                OR ts.attendance_status = \'present\')
           AND s.parent_id IS NOT NULL
           AND (:cutoff_trip_type <> \'afternoon\' OR ts.status = \'pending\')'
    );
    foreach (array_slice($decisions, 0, 20) as $decision) {
        if (!is_array($decision)) continue;
        $type = (string) ($decision['type'] ?? '');
        $classification = (string) ($decision['status'] ?? 'normal');
        $audience = (string) ($decision['audience'] ?? 'none');
        if (!in_array($type, $allowedAnomalyTypes, true)
            || !in_array($classification, $allowedClassifications, true)
            || !in_array($audience, $allowedAudiences, true)) {
            continue;
        }
        $reason = substr((string) ($decision['reason'] ?? 'Behavior evaluated.'), 0, 500);
        $eventOccurrence = match ($type) {
            'long_stop' => 'stop-'
                . ($stopEventId > 0 ? $stopEventId : $stopStartedAt),
            'route_deviation' => 'deviation-'
                . ($routeDeviationEventId > 0
                    ? $routeDeviationEventId : 'legacy'),
            'emergency_stop' => 'emergency-'
                . ($emergencyEventId > 0
                    ? $emergencyEventId
                    : ($stopEventId > 0 ? $stopEventId : 'legacy')),
            'overspeed' => 'overspeed-'
                . ($overspeedEventId > 0 ? $overspeedEventId : 'legacy'),
            default => 'trip',
        };
        $dedupKey = implode(':', [
            'anomaly', $tripId, $type, $classification, $audience,
            $eventOccurrence,
        ]);
        $insertAnomaly->execute([
            'trip_id' => $tripId,
            'anomaly_type' => $type,
            'classification' => $classification,
            'isolation_status' => $isolationStatus,
            'isolation_score' => $isolationScore,
            'audience' => $audience,
            'reason' => $reason,
            'decision_data' => json_encode(
                $decision,
                JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE
            ),
            'dedup_key' => $dedupKey,
        ]);
        $wasInserted = $insertAnomaly->rowCount() > 0;
        if ($wasInserted) $newAnomalyEvents++;

        // Insert into notifications table for parents whenever an alert is active
        if (!empty($decision['notify_parent']) || !empty($decision['alert'])) {
            $notificationMessage = !empty($decision['reason'])
                ? (string) $decision['reason']
                : match ($type) {
                    'emergency_stop' => 'Emergency alert: the school van has made an emergency stop.',
                    'overspeed' => 'Speed alert: the school van exceeded its configured speed limit.',
                    'route_deviation' => 'Route alert: the school van moved off-route.',
                    'long_stop' => 'Stop alert: the school van has remained stopped unusually long.',
                    default => 'Safety alert: vehicle behavior requires attention.',
                };
            $insertParentNotification->execute([
                'trip_id' => $tripId,
                'notification_type' => $type,
                'message' => $notificationMessage,
                'dedup_prefix' => 'parent-alert:' . $tripId . ':' . $type
                    . ':' . $eventOccurrence . ':' . $classification . ':',
                'source_trip_id' => $tripId,
                'eligibility_trip_type' => $tripType,
                'cutoff_trip_type' => $tripType,
            ]);
        }
    }

    if ($databaseStatus === 'completed') {
        $label = $pdo->prepare(
            'UPDATE trip_telemetry
             SET actual_remaining_sec = GREATEST(
                 0, :completed_duration - simulated_time_sec
             )
             WHERE trip_id = :trip_id'
        );
        $label->execute([
            'completed_duration' => $simulatedElapsed,
            'trip_id' => $tripId,
        ]);
    }

    $pdo->commit();
} catch (Throwable $exception) {
    if ($pdo->inTransaction()) $pdo->rollBack();
    json_result(['error' => 'Database synchronization failed.'], 500);
}

$maximum = $pdo->prepare(
    'SELECT COALESCE(MAX(sample_index), -1)
     FROM trip_telemetry WHERE trip_id = :trip_id'
);
$maximum->execute(['trip_id' => $tripId]);
json_result([
    'ok' => true,
    'last_saved_sample' => (int) $maximum->fetchColumn(),
    'status' => $databaseStatus,
    'new_anomaly_events' => $newAnomalyEvents,
]);
