<?php
declare(strict_types=1);

require_once dirname(__DIR__) . '/config/app.php';
require_once dirname(__DIR__) . '/config/database.php';
require_once dirname(__DIR__) . '/includes/auth.php';
require_once dirname(__DIR__) . '/includes/layout.php';

require_role('parent');

$statement = database()->prepare(
    'SELECT s.name AS student_name, s.pickup_location,
            s.pickup_lat, s.pickup_lng,
            v.van_number, u.name AS driver_name, d.phone AS driver_phone
     FROM students s
     JOIN vans v ON v.id = s.van_id
     LEFT JOIN drivers d ON d.van_id = v.id
     LEFT JOIN users u ON u.id = d.user_id
     WHERE s.parent_id = :parent_id AND s.active = 1
     ORDER BY s.id'
);
$statement->execute(['parent_id' => $_SESSION['user_id']]);
$students = $statement->fetchAll();

render_header('Parent dashboard');
?>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<div class="page-heading">
    <div>
        <span class="eyebrow">Parent</span>
        <h1>Student tracking</h1>
        <p>Follow the assigned van, route direction and live Random Forest ETA.</p>
    </div>
</div>

<?php if (!$students): ?>
    <div class="alert">No student is assigned to this parent account yet.</div>
<?php else: ?>
    <section class="panel">
        <div class="simulation-status-row">
            <div>
                <h2>Live van location</h2>
                <p class="muted" id="parent-live-description">Checking for an active trip…</p>
            </div>
            <span id="parent-live-status" class="status-badge">Checking</span>
        </div>
        <div id="parent-live-map"></div>
        <div class="parent-live-summary eta-only-summary">
            <div class="eta-summary-card"><span>RF ETA</span><strong id="parent-live-eta">—</strong></div>
        </div>
        <p class="muted parent-eta-note" id="parent-eta-method">
            Loading the ETA model…
        </p>
    </section>

    <section class="card-grid">
        <?php foreach ($students as $student): ?>
            <article class="panel">
                <h2>🎒 <?= escape($student['student_name']) ?></h2>
                <dl class="details">
                    <div><dt>Pickup</dt><dd><?= escape($student['pickup_location']) ?></dd></div>
                    <div><dt>Van</dt><dd><?= escape($student['van_number']) ?></dd></div>
                    <div><dt>Driver</dt><dd><?= escape($student['driver_name'] ?? 'Not assigned') ?></dd></div>
                    <div><dt>Phone</dt><dd><?= escape($student['driver_phone'] ?? '—') ?></dd></div>
                    <div><dt>Current ETA</dt><dd>Waiting for trip</dd></div>
                </dl>
            </article>
        <?php endforeach; ?>
    </section>

    <section class="panel">
        <div class="simulation-status-row">
            <div>
                <h2>Safety notifications</h2>
            </div>
            <span class="status-badge">Parent</span>
        </div>
        <div id="parent-notification-list" class="parent-notification-list">
            <p class="muted" id="parent-notification-empty">No safety alerts.</p>
        </div>
    </section>
    <div id="parent-safety-toasts" class="parent-safety-toasts"
         aria-live="polite"></div>
    <script>
    window.VAN_TRACKER_PARENT_LIVE = <?= json_encode([
        'apiUrl' => APP_BASE_URL . '/api/parent-live-trip.php',
        'routingUrl' => ROUTING_SERVICE_URL,
        'initialLat' => (float) $students[0]['pickup_lat'],
        'initialLng' => (float) $students[0]['pickup_lng'],
    ], JSON_UNESCAPED_SLASHES) ?>;
    window.VAN_TRACKER_PARENT_NOTIFICATIONS = <?= json_encode([
        'apiUrl' => APP_BASE_URL . '/api/parent-notifications.php',
        'viewerId' => (int) $_SESSION['user_id'],
    ], JSON_UNESCAPED_SLASHES) ?>;
    </script>
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <script src="<?= APP_BASE_URL ?>/assets/js/live-route.js?v=16"></script>
    <script src="<?= APP_BASE_URL ?>/assets/js/parent-live.js?v=16"></script>
    <script src="<?= APP_BASE_URL ?>/assets/js/parent-notifications.js?v=16"></script>
<?php endif; ?>
<?php render_footer(); ?>
