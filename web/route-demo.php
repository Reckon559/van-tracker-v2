<?php
declare(strict_types=1);

require_once __DIR__ . '/config/app.php';
require_once __DIR__ . '/includes/auth.php';
require_once __DIR__ . '/includes/layout.php';

require_any_role(['admin', 'driver']);
render_header('A* route demo');
if ($_SESSION['user_role'] === 'admin') {
    render_admin_navigation('route-demo');
}
?>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">

<div class="page-heading">
    <div>
        <span class="eyebrow">A* + Random Forest</span>
        <h1>Kathmandu route and ETA lab</h1>
        <p>Choose two points, calculate the road route, then estimate ETA for a selected scenario.</p>
    </div>
    <span id="service-state" class="service-pill">Checking routing service…</span>
</div>

<section class="route-layout">
    <aside class="panel route-controls">
        <form id="route-form" class="stack-form">
            <fieldset>
                <legend>Origin</legend>
                <label>Latitude <input id="origin-lat" type="number" step="any" value="27.735400" required></label>
                <label>Longitude <input id="origin-lng" type="number" step="any" value="85.302100" required></label>
            </fieldset>

            <fieldset>
                <legend>Destination</legend>
                <label>Latitude <input id="destination-lat" type="number" step="any" value="27.693100" required></label>
                <label>Longitude <input id="destination-lng" type="number" step="any" value="85.281100" required></label>
            </fieldset>

            <label>
                Search algorithm
                <select id="algorithm">
                    <option value="astar">A*</option>
                    <option value="dijkstra">Dijkstra reference</option>
                </select>
            </label>

            <div class="scenario-form-grid">
                <label>Traffic
                    <select id="eta-traffic">
                        <option value="low">Low</option>
                        <option value="medium" selected>Medium</option>
                        <option value="high">Heavy</option>
                    </select>
                </label>
                <label>Weather
                    <select id="eta-weather">
                        <option value="clear" selected>Clear</option>
                        <option value="rain">Rain</option>
                        <option value="heavy_rain">Heavy rain</option>
                        <option value="fog">Fog</option>
                    </select>
                </label>
                <label>School schedule
                    <select id="eta-school-period">
                        <option value="regular" selected>Regular</option>
                        <option value="exam">Exam</option>
                        <option value="half_day">Half-day</option>
                    </select>
                </label>
                <label>Student stops
                    <input id="eta-stops" type="number" min="0" max="30" value="4">
                </label>
                <label>Hour
                    <input id="eta-hour" type="number" min="0" max="23"
                           value="<?= (int) (new DateTimeImmutable('now', new DateTimeZone('Asia/Kathmandu')))->format('G') ?>">
                </label>
                <label>Day
                    <select id="eta-day">
                        <?php
                        $currentDay = (int) (new DateTimeImmutable('now', new DateTimeZone('Asia/Kathmandu')))->format('N') - 1;
                        foreach (['Mon','Tue','Wed','Thu','Fri','Sat','Sun'] as $index => $label):
                        ?>
                            <option value="<?= $index ?>" <?= $index === $currentDay ? 'selected' : '' ?>><?= $label ?></option>
                        <?php endforeach; ?>
                    </select>
                </label>
            </div>

            <button type="submit">Calculate route</button>
            <p class="muted click-help">Map clicks alternate between origin and destination.</p>
        </form>

        <div id="route-error" class="alert alert-danger" hidden></div>

        <dl class="route-results" id="route-results" hidden>
            <div><dt>Distance</dt><dd id="result-distance">—</dd></div>
            <div><dt>OSM baseline time</dt><dd id="result-duration">—</dd></div>
            <div class="eta-highlight"><dt>RF predicted ETA</dt><dd id="result-rf-eta">—</dd></div>
            <div><dt>Prediction range</dt><dd id="result-rf-range">—</dd></div>
            <div><dt>Dominant road</dt><dd id="result-road-type">—</dd></div>
            <div><dt>Visited nodes</dt><dd id="result-visited">—</dd></div>
            <div><dt>Search runtime</dt><dd id="result-runtime">—</dd></div>
        </dl>
    </aside>

    <section class="panel map-panel">
        <div id="route-map" aria-label="Kathmandu route map"></div>
    </section>
</section>

<script>
window.VAN_TRACKER_ROUTING_URL = <?= json_encode(ROUTING_SERVICE_URL, JSON_UNESCAPED_SLASHES) ?>;
</script>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="<?= APP_BASE_URL ?>/assets/js/route-demo.js?v=12"></script>
<?php render_footer(); ?>
