<?php
declare(strict_types=1);

require_once dirname(__DIR__) . '/config/app.php';
require_once dirname(__DIR__) . '/config/database.php';
require_once dirname(__DIR__) . '/includes/auth.php';
require_once dirname(__DIR__) . '/includes/layout.php';

require_role('driver');

$statement = database()->prepare(
    'SELECT d.phone, v.van_number, v.plate_number, v.speed_limit_kmh
     FROM drivers d
     LEFT JOIN vans v ON v.id = d.van_id
     WHERE d.user_id = :user_id'
);
$statement->execute(['user_id' => $_SESSION['user_id']]);
$driver = $statement->fetch();

$assignedStatement = database()->prepare(
    "SELECT t.id, t.trip_type, t.status, r.name AS route_name,
            v.van_number, t.scenario_hour_of_day,
            SUM(ts.student_id IS NOT NULL) AS student_count,
            SUM(ts.student_id IS NOT NULL AND ts.attendance_status = 'unmarked') AS unmarked_count
     FROM trips t
     JOIN drivers d ON d.id = t.driver_id
     JOIN routes r ON r.id = t.route_id
     JOIN vans v ON v.id = t.van_id
     LEFT JOIN trip_stops ts ON ts.trip_id = t.id
     WHERE d.user_id = :user_id
       AND t.status IN ('scheduled','active','paused','emergency')
     GROUP BY t.id
     ORDER BY t.id DESC"
);
$assignedStatement->execute(['user_id' => $_SESSION['user_id']]);
$assignedTrips = $assignedStatement->fetchAll();
$currentTrip = $assignedTrips[0] ?? null;
$latestTripId = $currentTrip ? (int) $currentTrip['id'] : null;

render_header('Driver dashboard');
render_driver_navigation('dashboard');
?>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<div class="page-heading">
    <div>
        <span class="eyebrow">Driver</span>
        <h1>Trip control</h1>
        <p>Monitor the A* route, movement direction and Random Forest ETA in one view.</p>
    </div>
    <div class="inline-actions">
        <?php if ($latestTripId !== null): ?>
            <a class="primary-button" href="<?= APP_BASE_URL ?>/trip-control.php?trip_id=<?= $latestTripId ?>">Open assigned trip</a>
        <?php endif; ?>
        <a class="primary-button secondary-button" href="<?= APP_BASE_URL ?>/driver/trip-history.php">View trip history</a>
    </div>
</div>

<section class="metric-grid">
    <?php
    status_card('Assigned van', $driver['van_number'] ?? 'Not assigned');
    status_card('Plate number', $driver['plate_number'] ?? '—');
    status_card('Speed limit', isset($driver['speed_limit_kmh']) ? $driver['speed_limit_kmh'] . ' km/h' : '—');
    status_card('Trip status', 'See live panel');
    ?>
</section>

<section class="panel">
    <h2>Current administrator assignment</h2>
    <?php if ($currentTrip === null): ?>
        <p class="muted">No morning or afternoon trip is currently assigned.</p>
    <?php else: ?>
        <article class="driver-trip-card">
            <div>
                <strong>#<?= (int) $currentTrip['id'] ?> · <?= escape(ucfirst($currentTrip['trip_type'])) ?></strong>
                <span><?= escape($currentTrip['route_name']) ?> · <?= escape($currentTrip['van_number']) ?></span>
                <small><?php if ($currentTrip['trip_type'] === 'morning'): ?>Ready to start morning pickup<?php else: ?><?= (int) $currentTrip['unmarked_count'] === 0 ? 'Attendance recorded' : 'Attendance required before start' ?><?php endif; ?></small>
            </div>
            <a class="primary-button" href="<?= APP_BASE_URL ?>/trip-control.php?trip_id=<?= (int) $currentTrip['id'] ?>">
                <?= $currentTrip['status'] === 'scheduled' && $currentTrip['trip_type'] === 'afternoon' ? 'Take attendance' : 'Open controls' ?>
            </a>
        </article>
    <?php endif; ?>
</section>

<section class="panel">
    <div class="simulation-status-row">
        <h2>Notifications</h2>
        <span class="status-badge">Driver</span>
    </div>
    <div id="driver-notification-list" class="driver-notification-list">
        <p class="muted">Loading notifications…</p>
    </div>
</section>
<div id="driver-notification-toasts" class="parent-safety-toasts"
     aria-live="polite"></div>

<section class="panel">
    <div class="simulation-status-row">
        <div>
            <h2>Live assigned route</h2>
            <p class="muted" id="driver-live-description">
                Checking for an assigned trip…
            </p>
        </div>
        <span id="driver-live-status" class="status-badge">Checking</span>
    </div>
    <div id="driver-live-map"></div>
    <div class="driver-live-summary">
        <div><span>Speed</span><strong id="driver-live-speed">—</strong></div>
        <div><span>Progress</span><strong id="driver-live-progress">—</strong></div>
        <div class="eta-summary-card"><span>RF route ETA</span><strong id="driver-live-eta">—</strong></div>
        <div><span>Prediction range</span><strong id="driver-live-eta-range">—</strong></div>
        <div><span>Next stop</span><strong id="driver-live-next-stop">—</strong></div>
    </div>
    <p class="muted parent-eta-note" id="driver-eta-method">Loading ETA model…</p>
</section>

<script>
window.VAN_TRACKER_DRIVER_LIVE = <?= json_encode([
    'apiUrl' => APP_BASE_URL . '/api/driver-live-trip.php',
    'routingUrl' => ROUTING_SERVICE_URL,
], JSON_UNESCAPED_SLASHES) ?>;
window.VAN_TRACKER_DRIVER_NOTIFICATIONS = <?= json_encode([
    'apiUrl' => APP_BASE_URL . '/api/driver-notifications.php',
    'viewerId' => (int) $_SESSION['user_id'],
    'surface' => 'dashboard',
], JSON_UNESCAPED_SLASHES) ?>;
</script>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="<?= APP_BASE_URL ?>/assets/js/live-route.js?v=16"></script>
<script src="<?= APP_BASE_URL ?>/assets/js/driver-live.js?v=16"></script>
<script src="<?= APP_BASE_URL ?>/assets/js/driver-notifications.js?v=16"></script>
<?php render_footer(); ?>
