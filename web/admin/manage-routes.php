<?php
declare(strict_types=1);

require_once dirname(__DIR__) . '/config/app.php';
require_once dirname(__DIR__) . '/config/database.php';
require_once dirname(__DIR__) . '/includes/auth.php';
require_once dirname(__DIR__) . '/includes/layout.php';

require_role('admin');
$pdo = database();
$errors = [];
$form = [
    'route_id' => '',
    'name' => '',
    'start_name' => '',
    'start_lat' => '',
    'start_lng' => '',
    'school_name' => '',
    'school_lat' => '',
    'school_lng' => '',
];

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    verify_csrf();
    $action = (string) ($_POST['action'] ?? '');

    if ($action === 'toggle') {
        $routeId = positive_int($_POST['route_id'] ?? null);
        if ($routeId !== null) {
            $statement = $pdo->prepare(
                'UPDATE routes SET active = IF(active = 1, 0, 1) WHERE id = :id'
            );
            $statement->execute(['id' => $routeId]);
            set_flash('success', 'Route status updated.');
        }
        redirect('/admin/manage-routes.php');
    }

    if ($action === 'save') {
        foreach (array_keys($form) as $field) {
            $form[$field] = trim((string) ($_POST[$field] ?? ''));
        }
        $routeId = $form['route_id'] === '' ? null : positive_int($form['route_id']);
        $startLat = valid_coordinate($form['start_lat'], -90, 90);
        $startLng = valid_coordinate($form['start_lng'], -180, 180);
        $schoolLat = valid_coordinate($form['school_lat'], -90, 90);
        $schoolLng = valid_coordinate($form['school_lng'], -180, 180);

        if ($form['name'] === '') $errors[] = 'Route name is required.';
        if ($form['start_name'] === '') $errors[] = 'Starting-point name is required.';
        if ($startLat === null || $startLng === null) {
            $errors[] = 'Select a valid route starting point.';
        }
        if ($form['school_name'] === '') $errors[] = 'School name is required.';
        if ($schoolLat === null || $schoolLng === null) {
            $errors[] = 'Select a valid school point.';
        }

        if (!$errors) {
            if ($routeId === null) {
                $statement = $pdo->prepare(
                    'INSERT INTO routes
                        (name, start_name, start_lat, start_lng,
                         school_name, school_lat, school_lng)
                     VALUES
                        (:name, :start_name, :start_lat, :start_lng,
                         :school_name, :school_lat, :school_lng)'
                );
            } else {
                $statement = $pdo->prepare(
                    'UPDATE routes
                     SET name = :name, start_name = :start_name,
                         start_lat = :start_lat, start_lng = :start_lng,
                         school_name = :school_name,
                         school_lat = :school_lat, school_lng = :school_lng
                     WHERE id = :id'
                );
            }
            $parameters = [
                'name' => $form['name'],
                'start_name' => $form['start_name'],
                'start_lat' => $startLat,
                'start_lng' => $startLng,
                'school_name' => $form['school_name'],
                'school_lat' => $schoolLat,
                'school_lng' => $schoolLng,
            ];
            if ($routeId !== null) $parameters['id'] = $routeId;
            $statement->execute($parameters);
            set_flash('success', $routeId === null ? 'Route created.' : 'Route updated.');
            redirect('/admin/manage-routes.php');
        }
    }
}

$editId = positive_int($_GET['edit'] ?? null);
if ($_SERVER['REQUEST_METHOD'] !== 'POST' && $editId !== null) {
    $statement = $pdo->prepare(
        'SELECT id AS route_id, name, start_name, start_lat, start_lng,
                school_name, school_lat, school_lng
         FROM routes WHERE id = :id'
    );
    $statement->execute(['id' => $editId]);
    if ($record = $statement->fetch()) {
        foreach ($record as $key => $value) {
            $form[$key] = $value === null ? '' : (string) $value;
        }
    }
}

$routes = $pdo->query(
    'SELECT r.*,
            (SELECT COUNT(*) FROM route_students rs WHERE rs.route_id = r.id) AS stop_count
     FROM routes r ORDER BY r.active DESC, r.name'
)->fetchAll();

render_header('Manage routes');
render_admin_navigation('routes');
?>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<div class="page-heading">
    <div>
        <span class="eyebrow">Administrator</span>
        <h1>Manage routes</h1>
        <p>Define the depot and school before assigning student stops.</p>
    </div>
</div>

<section class="panel">
    <h2><?= $form['route_id'] === '' ? 'Create route' : 'Edit route' ?></h2>
    <?php render_form_errors($errors); ?>
    <form method="post" class="form-grid">
        <input type="hidden" name="csrf_token" value="<?= csrf_token() ?>">
        <input type="hidden" name="action" value="save">
        <input type="hidden" name="route_id" value="<?= escape($form['route_id']) ?>">
        <label class="full-width">Route name
            <input name="name" value="<?= escape($form['name']) ?>"
                   placeholder="Kalanki morning route" required>
        </label>

        <div class="location-picker"
             data-location-picker data-name-input="start-name"
             data-lat-input="start-lat" data-lng-input="start-lng">
            <h3>1. Van starting point / depot</h3>
            <div class="location-search-row">
                <input data-role="search" placeholder="Search starting place"
                       value="<?= escape($form['start_name']) ?>">
                <button type="button" data-role="search-button">Search</button>
            </div>
            <div class="location-results" data-role="results"></div>
            <label>Name
                <input id="start-name" name="start_name"
                       value="<?= escape($form['start_name']) ?>" required>
            </label>
            <div class="coordinate-grid">
                <label>Latitude
                    <input id="start-lat" name="start_lat" type="number" step="any"
                           value="<?= escape($form['start_lat']) ?>" required>
                </label>
                <label>Longitude
                    <input id="start-lng" name="start_lng" type="number" step="any"
                           value="<?= escape($form['start_lng']) ?>" required>
                </label>
            </div>
            <div class="location-map" data-role="map"></div>
        </div>

        <div class="location-picker"
             data-location-picker data-name-input="school-name"
             data-lat-input="school-lat" data-lng-input="school-lng">
            <h3>2. Destination school</h3>
            <div class="location-search-row">
                <input data-role="search" placeholder="Search school"
                       value="<?= escape($form['school_name']) ?>">
                <button type="button" data-role="search-button">Search</button>
            </div>
            <div class="location-results" data-role="results"></div>
            <label>Name
                <input id="school-name" name="school_name"
                       value="<?= escape($form['school_name']) ?>" required>
            </label>
            <div class="coordinate-grid">
                <label>Latitude
                    <input id="school-lat" name="school_lat" type="number" step="any"
                           value="<?= escape($form['school_lat']) ?>" required>
                </label>
                <label>Longitude
                    <input id="school-lng" name="school_lng" type="number" step="any"
                           value="<?= escape($form['school_lng']) ?>" required>
                </label>
            </div>
            <div class="location-map" data-role="map"></div>
        </div>

        <div class="inline-actions full-width">
            <button type="submit"><?= $form['route_id'] === '' ? 'Create route' : 'Save changes' ?></button>
            <?php if ($form['route_id'] !== ''): ?>
                <a class="primary-button secondary-button" href="<?= APP_BASE_URL ?>/admin/manage-routes.php">Cancel</a>
            <?php endif; ?>
        </div>
    </form>
</section>

<section class="panel">
    <h2>All routes</h2>
    <div class="data-table-wrap">
        <table class="data-table">
            <thead><tr>
                <th>Route</th><th>Start</th><th>School</th><th>Stops</th>
                <th>Status</th><th>Actions</th>
            </tr></thead>
            <tbody>
            <?php foreach ($routes as $route): ?>
                <tr>
                    <td><?= escape($route['name']) ?></td>
                    <td><?= escape($route['start_name']) ?></td>
                    <td><?= escape($route['school_name']) ?></td>
                    <td><?= (int) $route['stop_count'] ?></td>
                    <td><span class="status-badge <?= $route['active'] ? '' : 'inactive' ?>">
                        <?= $route['active'] ? 'Active' : 'Inactive' ?>
                    </span></td>
                    <td><div class="inline-actions">
                        <a class="primary-button small-button"
                           href="<?= APP_BASE_URL ?>/admin/route-stops.php?route_id=<?= (int) $route['id'] ?>">
                            Stops
                        </a>
                        <a class="primary-button small-button secondary-button"
                           href="?edit=<?= (int) $route['id'] ?>">Edit</a>
                        <form method="post">
                            <input type="hidden" name="csrf_token" value="<?= csrf_token() ?>">
                            <input type="hidden" name="action" value="toggle">
                            <input type="hidden" name="route_id" value="<?= (int) $route['id'] ?>">
                            <button class="small-button <?= $route['active'] ? 'danger-button' : '' ?>">
                                <?= $route['active'] ? 'Deactivate' : 'Activate' ?>
                            </button>
                        </form>
                    </div></td>
                </tr>
            <?php endforeach; ?>
            </tbody>
        </table>
    </div>
</section>

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="<?= APP_BASE_URL ?>/assets/js/location-picker.js"></script>
<?php render_footer(); ?>
