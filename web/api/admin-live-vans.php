<?php
declare(strict_types=1);

require_once dirname(__DIR__) . '/config/app.php';
require_once dirname(__DIR__) . '/config/database.php';
require_once dirname(__DIR__) . '/includes/auth.php';
require_once dirname(__DIR__) . '/includes/trips.php';

require_role('admin');
header('Cache-Control: no-store, no-cache, must-revalidate');
$rows = database()->query(
    "SELECT v.id AS van_id, v.van_number, v.plate_number,
            v.speed_limit_kmh, u.name AS driver_name,
            t.id AS trip_id, t.status, t.trip_type,
            t.current_lat, t.current_lng, t.physical_speed_kmh,
            t.heading_deg, t.distance_travelled_m, t.total_distance_m,
            r.name AS route_name
     FROM vans v
     LEFT JOIN drivers d ON d.van_id = v.id
     LEFT JOIN users u ON u.id = d.user_id
     LEFT JOIN trips t ON t.id = (
         SELECT MAX(latest.id) FROM trips latest WHERE latest.van_id = v.id
     )
     LEFT JOIN routes r ON r.id = t.route_id
     WHERE v.active = 1
     ORDER BY v.van_number"
)->fetchAll();

$vans = array_map(static function (array $row): array {
    $total = max(0.0, (float) ($row['total_distance_m'] ?? 0));
    $travelled = max(0.0, (float) ($row['distance_travelled_m'] ?? 0));
    $hasLocation = $row['current_lat'] !== null && $row['current_lng'] !== null;
    $status = $row['status'] !== null ? (string) $row['status'] : 'idle';
    return [
        'van_id' => (int) $row['van_id'],
        'van_number' => $row['van_number'],
        'plate_number' => $row['plate_number'],
        'driver_name' => $row['driver_name'] ?: 'Unassigned',
        'trip_id' => $row['trip_id'] !== null ? (int) $row['trip_id'] : null,
        'trip_type' => $row['trip_type'],
        'route_name' => $row['route_name'],
        'status' => $status,
        'has_location' => $hasLocation,
        'latitude' => $hasLocation ? (float) $row['current_lat'] : null,
        'longitude' => $hasLocation ? (float) $row['current_lng'] : null,
        'speed_kmh' => in_array($status, ['active'], true)
            ? (float) $row['physical_speed_kmh'] : 0.0,
        'speed_limit_kmh' => (float) $row['speed_limit_kmh'],
        'heading_deg' => (float) ($row['heading_deg'] ?? 0),
        'progress' => $total > 0 ? min(1.0, $travelled / $total) : 0.0,
    ];
}, $rows);

json_result(['vans' => $vans]);
