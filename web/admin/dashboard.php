<?php
declare(strict_types=1);

require_once dirname(__DIR__) . '/config/app.php';
require_once dirname(__DIR__) . '/config/database.php';
require_once dirname(__DIR__) . '/includes/auth.php';
require_once dirname(__DIR__) . '/includes/layout.php';

require_role('admin');

$pdo = database();
$counts = [
    'Vans' => (int) $pdo->query('SELECT COUNT(*) FROM vans WHERE active = 1')->fetchColumn(),
    'Drivers' => (int) $pdo->query('SELECT COUNT(*) FROM drivers')->fetchColumn(),
    'Students' => (int) $pdo->query('SELECT COUNT(*) FROM students WHERE active = 1')->fetchColumn(),
    'Active trips' => (int) $pdo->query("SELECT COUNT(*) FROM trips WHERE status IN ('active','paused','emergency')")->fetchColumn(),
];

render_header('Administrator dashboard');
render_admin_navigation('dashboard');
?>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<div class="page-heading">
    <div>
        <span class="eyebrow">Administrator</span>
        <h1>Operations overview</h1>
        <p>Monitor routes, simulations and the trained Kathmandu ETA model.</p>
    </div>
    <div class="inline-actions">
        <a class="primary-button" href="<?= APP_BASE_URL ?>/admin/manage-trips.php">Create trip</a>
        <a class="primary-button secondary-button" href="<?= APP_BASE_URL ?>/route-demo.php">Test ETA model</a>
    </div>
</div>

<section class="metric-grid">
    <?php foreach ($counts as $label => $value) status_card($label, $value); ?>
</section>

<section class="panel">
    <div class="simulation-status-row">
        <div>
            <h2>All vans</h2>
            <p class="muted" id="admin-fleet-count">Loading fleet…</p>
        </div>
        <a class="primary-button secondary-button"
           href="<?= APP_BASE_URL ?>/admin/trip-history.php">View trip history</a>
    </div>
    <div class="admin-fleet-layout">
        <div id="admin-fleet-map"></div>
        <div id="admin-fleet-list" class="admin-fleet-list"></div>
    </div>
</section>

<section class="panel">
    <div class="simulation-status-row">
        <div>
            <h2>Suspicious activity</h2>
            <p class="muted" id="admin-anomaly-count">Loading alerts…</p>
        </div>
        <span class="status-badge">Transport staff</span>
    </div>
    <div id="admin-anomaly-list" class="admin-anomaly-list"></div>
</section>
<div id="admin-alert-toasts" class="parent-safety-toasts"
     aria-live="polite"></div>

<section class="panel model-overview">
    <div class="simulation-status-row">
        <div>
            <h2>Random Forest ETA model</h2>
            <p class="muted">Synthetic scenarios grounded in the local Kathmandu OSM graph.</p>
        </div>
        <span id="admin-model-status" class="service-pill">Checking model…</span>
    </div>
    <div class="model-metric-grid">
        <div><span>Dataset</span><strong id="admin-model-rows">—</strong></div>
        <div><span>Independent trips</span><strong id="admin-model-trips">—</strong></div>
        <div><span>Test MAE</span><strong id="admin-model-mae">—</strong></div>
        <div><span>Test R²</span><strong id="admin-model-r2">—</strong></div>
    </div>
</section>

<script>
(async function () {
    const status = document.getElementById('admin-model-status');
    try {
        const response = await fetch(<?= json_encode(ROUTING_SERVICE_URL . '/api/eta/health', JSON_UNESCAPED_SLASHES) ?>);
        const data = await response.json();
        if (!response.ok || !data.available) throw new Error('Model unavailable');
        status.textContent = 'Model ready';
        status.className = 'service-pill ready';
        document.getElementById('admin-model-rows').textContent =
            Number(data.dataset_rows).toLocaleString() + ' rows';
        document.getElementById('admin-model-trips').textContent =
            Number(data.trip_count).toLocaleString();
        document.getElementById('admin-model-mae').textContent =
            Number(data.mae_sec).toFixed(1) + ' sec';
        document.getElementById('admin-model-r2').textContent =
            Number(data.r2).toFixed(3);
    } catch (_error) {
        status.textContent = 'Model offline';
        status.className = 'service-pill offline';
    }
})();
</script>
<script>
window.VAN_TRACKER_ADMIN_FLEET = <?= json_encode([
    'apiUrl' => APP_BASE_URL . '/api/admin-live-vans.php',
], JSON_UNESCAPED_SLASHES) ?>;
window.VAN_TRACKER_ADMIN_ALERTS = <?= json_encode([
    'apiUrl' => APP_BASE_URL . '/api/admin-anomalies.php',
    'viewerId' => (int) $_SESSION['user_id'],
], JSON_UNESCAPED_SLASHES) ?>;
</script>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="<?= APP_BASE_URL ?>/assets/js/admin-fleet.js?v=16"></script>
<script src="<?= APP_BASE_URL ?>/assets/js/admin-alerts.js?v=16"></script>
<?php render_footer(); ?>
