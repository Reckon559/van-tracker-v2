<?php
declare(strict_types=1);

require_once dirname(__DIR__) . '/config/app.php';
require_once dirname(__DIR__) . '/config/database.php';
require_once dirname(__DIR__) . '/includes/auth.php';
require_once dirname(__DIR__) . '/includes/layout.php';

require_role('admin');
$pdo = database();
$routes = $pdo->query(
    'SELECT * FROM routes WHERE active = 1 ORDER BY name'
)->fetchAll();

$routeId = positive_int($_POST['route_id'] ?? $_GET['route_id'] ?? null);
if ($routeId === null && $routes) {
    $routeId = (int) $routes[0]['id'];
}

$route = null;
if ($routeId !== null) {
    $statement = $pdo->prepare('SELECT * FROM routes WHERE id = :id');
    $statement->execute(['id' => $routeId]);
    $route = $statement->fetch() ?: null;
}

function straight_line_distance(array $from, array $to): float
{
    $earthRadiusM = 6_371_008.8;
    $lat1 = deg2rad((float) $from['lat']);
    $lat2 = deg2rad((float) $to['lat']);
    $deltaLat = deg2rad((float) $to['lat'] - (float) $from['lat']);
    $deltaLng = deg2rad((float) $to['lng'] - (float) $from['lng']);
    $value = sin($deltaLat / 2) ** 2
        + cos($lat1) * cos($lat2) * sin($deltaLng / 2) ** 2;
    return 2 * $earthRadiusM * asin(sqrt($value));
}

function nearest_neighbour_order(array $start, array $stops): array
{
    $ordered = [];
    $remaining = array_values($stops);
    $current = $start;

    while ($remaining) {
        $bestIndex = 0;
        $bestDistance = INF;
        foreach ($remaining as $index => $stop) {
            $distance = straight_line_distance($current, $stop);
            if ($distance < $bestDistance) {
                $bestDistance = $distance;
                $bestIndex = $index;
            }
        }
        $current = $remaining[$bestIndex];
        $ordered[] = $current;
        array_splice($remaining, $bestIndex, 1);
    }
    return $ordered;
}

function ordering_distance(array $start, array $school, array $stops): float
{
    $distance = 0.0;
    $current = $start;
    foreach ($stops as $stop) {
        $distance += straight_line_distance($current, $stop);
        $current = $stop;
    }
    return $distance + straight_line_distance($current, $school);
}

function improve_with_two_opt(array $start, array $school, array $stops): array
{
    if (count($stops) < 3) {
        return $stops;
    }

    $best = array_values($stops);
    $bestDistance = ordering_distance($start, $school, $best);
    $improved = true;
    $passes = 0;

    while ($improved && $passes < 25) {
        $improved = false;
        $passes++;
        $count = count($best);
        for ($left = 0; $left < $count - 1; $left++) {
            for ($right = $left + 1; $right < $count; $right++) {
                $candidate = array_merge(
                    array_slice($best, 0, $left),
                    array_reverse(array_slice($best, $left, $right - $left + 1)),
                    array_slice($best, $right + 1)
                );
                $candidateDistance = ordering_distance($start, $school, $candidate);
                if ($candidateDistance + 0.01 < $bestDistance) {
                    $best = $candidate;
                    $bestDistance = $candidateDistance;
                    $improved = true;
                }
            }
        }
    }
    return $best;
}

if ($_SERVER['REQUEST_METHOD'] === 'POST' && $route !== null) {
    verify_csrf();
    $action = (string) ($_POST['action'] ?? '');
    $rawStudentIds = $_POST['student_ids'] ?? [];
    $studentIds = [];
    if (is_array($rawStudentIds)) {
        foreach ($rawStudentIds as $rawId) {
            $id = positive_int($rawId);
            if ($id !== null) $studentIds[$id] = $id;
        }
    }
    $studentIds = array_values($studentIds);

    $selectedStudents = [];
    if ($studentIds) {
        $placeholders = implode(',', array_fill(0, count($studentIds), '?'));
        $statement = $pdo->prepare(
            "SELECT id, name, pickup_lat AS lat, pickup_lng AS lng
             FROM students WHERE active = 1 AND id IN ($placeholders)"
        );
        $statement->execute($studentIds);
        $selectedStudents = $statement->fetchAll();
    }

    if ($action === 'auto_order') {
        $start = ['lat' => $route['start_lat'], 'lng' => $route['start_lng']];
        $school = ['lat' => $route['school_lat'], 'lng' => $route['school_lng']];
        $selectedStudents = nearest_neighbour_order($start, $selectedStudents);
        $selectedStudents = improve_with_two_opt($start, $school, $selectedStudents);
        $message = 'Stops ordered using nearest neighbour and improved with 2-opt.';
    } else {
        $sequence = is_array($_POST['sequence'] ?? null) ? $_POST['sequence'] : [];
        usort($selectedStudents, static function (array $first, array $second) use ($sequence): int {
            $firstOrder = positive_int($sequence[$first['id']] ?? null) ?? PHP_INT_MAX;
            $secondOrder = positive_int($sequence[$second['id']] ?? null) ?? PHP_INT_MAX;
            return $firstOrder <=> $secondOrder ?: strcasecmp($first['name'], $second['name']);
        });
        $message = 'Route stops saved.';
    }

    $pdo->beginTransaction();
    try {
        $delete = $pdo->prepare('DELETE FROM route_students WHERE route_id = :route_id');
        $delete->execute(['route_id' => $routeId]);
        $insert = $pdo->prepare(
            'INSERT INTO route_students (route_id, student_id, stop_sequence)
             VALUES (:route_id, :student_id, :stop_sequence)'
        );
        foreach ($selectedStudents as $index => $student) {
            $insert->execute([
                'route_id' => $routeId,
                'student_id' => $student['id'],
                'stop_sequence' => $index + 1,
            ]);
        }
        $pdo->commit();
        set_flash('success', $message);
    } catch (Throwable $exception) {
        if ($pdo->inTransaction()) $pdo->rollBack();
        set_flash('danger', 'Stops could not be saved: ' . $exception->getMessage());
    }
    redirect('/admin/route-stops.php?route_id=' . $routeId);
}

$students = [];
$assignedStops = [];
if ($route !== null) {
    $statement = $pdo->prepare(
        'SELECT s.id, s.name, s.pickup_location, s.pickup_lat, s.pickup_lng,
                v.van_number, rs.stop_sequence
         FROM students s
         JOIN vans v ON v.id = s.van_id
         LEFT JOIN route_students rs
           ON rs.student_id = s.id AND rs.route_id = :route_id
         WHERE s.active = 1
         ORDER BY rs.stop_sequence IS NULL, rs.stop_sequence, s.name'
    );
    $statement->execute(['route_id' => $routeId]);
    $students = $statement->fetchAll();
    $assignedStops = array_values(array_filter(
        $students,
        static fn (array $student): bool => $student['stop_sequence'] !== null
    ));
}

$previewPoints = [];
if ($route !== null) {
    $previewPoints[] = [
        'name' => $route['start_name'],
        'lat' => (float) $route['start_lat'],
        'lng' => (float) $route['start_lng'],
        'type' => 'start',
    ];
    foreach ($assignedStops as $student) {
        $previewPoints[] = [
            'name' => $student['name'] . ' — ' . $student['pickup_location'],
            'lat' => (float) $student['pickup_lat'],
            'lng' => (float) $student['pickup_lng'],
            'type' => 'student',
        ];
    }
    $previewPoints[] = [
        'name' => $route['school_name'],
        'lat' => (float) $route['school_lat'],
        'lng' => (float) $route['school_lng'],
        'type' => 'school',
    ];
}

render_header('Route stops');
render_admin_navigation('routes');
?>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<div class="page-heading">
    <div>
        <span class="eyebrow">Route preparation</span>
        <h1>Assign and order student stops</h1>
        <p>Stop ordering chooses the visit sequence; A* then finds each road leg.</p>
    </div>
    <a class="primary-button secondary-button" href="<?= APP_BASE_URL ?>/admin/manage-routes.php">Back to routes</a>
</div>

<?php if (!$routes): ?>
    <div class="alert">Create an active route before assigning stops.</div>
<?php else: ?>
    <section class="panel">
        <form method="get">
            <label>Select route
                <select name="route_id" onchange="this.form.submit()">
                    <?php foreach ($routes as $routeOption): ?>
                        <option value="<?= (int) $routeOption['id'] ?>"
                            <?= (int) $routeOption['id'] === $routeId ? 'selected' : '' ?>>
                            <?= escape($routeOption['name']) ?>
                        </option>
                    <?php endforeach; ?>
                </select>
            </label>
        </form>
    </section>

    <?php if ($route !== null): ?>
        <section class="panel">
            <h2><?= escape($route['name']) ?></h2>
            <p class="muted">
                <?= escape($route['start_name']) ?> → student homes → <?= escape($route['school_name']) ?>
            </p>
            <form method="post">
                <input type="hidden" name="csrf_token" value="<?= csrf_token() ?>">
                <input type="hidden" name="route_id" value="<?= (int) $routeId ?>">
                <div class="data-table-wrap">
                    <table class="data-table">
                        <thead><tr>
                            <th>Include</th><th>Order</th><th>Student</th>
                            <th>Pickup</th><th>Assigned van</th>
                        </tr></thead>
                        <tbody>
                        <?php foreach ($students as $student): ?>
                            <tr>
                                <td>
                                    <input type="checkbox" name="student_ids[]"
                                           value="<?= (int) $student['id'] ?>"
                                           <?= $student['stop_sequence'] !== null ? 'checked' : '' ?>>
                                </td>
                                <td>
                                    <input class="stop-order-input" type="number" min="1"
                                           name="sequence[<?= (int) $student['id'] ?>]"
                                           value="<?= $student['stop_sequence'] !== null ? (int) $student['stop_sequence'] : '' ?>">
                                </td>
                                <td><?= escape($student['name']) ?></td>
                                <td><?= escape($student['pickup_location']) ?></td>
                                <td><?= escape($student['van_number']) ?></td>
                            </tr>
                        <?php endforeach; ?>
                        </tbody>
                    </table>
                </div>
                <div class="inline-actions form-actions">
                    <button type="submit" name="action" value="save_order">Save manual order</button>
                    <button type="submit" name="action" value="auto_order" class="secondary-button">
                        Auto-order with nearest neighbour + 2-opt
                    </button>
                </div>
            </form>
        </section>

        <section class="route-layout">
            <aside class="panel route-controls">
                <h2>A* road preview</h2>
                <p>The preview follows the saved stop order and calls A* for every leg.</p>
                <button id="preview-route" <?= count($previewPoints) < 2 ? 'disabled' : '' ?>>
                    Calculate complete route
                </button>
                <div id="preview-error" class="alert alert-danger" hidden></div>
                <dl class="route-results" id="preview-results" hidden>
                    <div><dt>Stops</dt><dd id="preview-stops">—</dd></div>
                    <div><dt>Road distance</dt><dd id="preview-distance">—</dd></div>
                    <div><dt>Baseline time</dt><dd id="preview-duration">—</dd></div>
                    <div><dt>A* legs</dt><dd id="preview-legs">—</dd></div>
                </dl>
            </aside>
            <section class="panel map-panel">
                <div id="route-stops-map"></div>
            </section>
        </section>
    <?php endif; ?>
<?php endif; ?>

<?php if ($route !== null): ?>
<script>
window.VAN_TRACKER_ROUTING_URL = <?= json_encode(ROUTING_SERVICE_URL, JSON_UNESCAPED_SLASHES) ?>;
window.VAN_TRACKER_ROUTE_POINTS = <?= json_encode($previewPoints, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE) ?>;
</script>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="<?= APP_BASE_URL ?>/assets/js/route-stops.js?v=12"></script>
<?php endif; ?>
<?php render_footer(); ?>
