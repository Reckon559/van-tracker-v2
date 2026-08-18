<?php
declare(strict_types=1);

require_once dirname(__DIR__) . '/config/app.php';
require_once dirname(__DIR__) . '/config/database.php';
require_once dirname(__DIR__) . '/includes/auth.php';
require_once dirname(__DIR__) . '/includes/layout.php';

require_role('admin');
$pdo = database();
$errors = [];

$drivers = $pdo->query(
    'SELECT d.id AS driver_id, u.name AS driver_name,
            v.id AS van_id, v.van_number, v.speed_limit_kmh
     FROM drivers d
     JOIN users u ON u.id = d.user_id
     JOIN vans v ON v.id = d.van_id
     WHERE u.active = 1 AND v.active = 1
     ORDER BY u.name'
)->fetchAll();
$driversById = array_column($drivers, null, 'driver_id');
$routes = $pdo->query(
    'SELECT r.*,
            (SELECT COUNT(*) FROM route_students rs WHERE rs.route_id = r.id) AS stop_count
     FROM routes r
     WHERE r.active = 1
     ORDER BY r.name'
)->fetchAll();

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    verify_csrf();
    $routeId = positive_int($_POST['route_id'] ?? null);
    $driverId = positive_int($_POST['driver_id'] ?? null);
    $tripType = (string) ($_POST['trip_type'] ?? '');
    $trafficLevel = (string) ($_POST['traffic_level'] ?? 'medium');
    $weather = (string) ($_POST['weather'] ?? 'clear');
    $schoolPeriod = (string) ($_POST['school_period'] ?? 'regular');
    $scenarioHour = filter_var($_POST['hour_of_day'] ?? null, FILTER_VALIDATE_INT);
    $scenarioDay = filter_var($_POST['day_of_week'] ?? null, FILTER_VALIDATE_INT);

    if ($routeId === null) $errors[] = 'Select a route.';
    if ($driverId === null || !isset($driversById[$driverId])) {
        $errors[] = 'Select an available driver and van.';
    }
    if (!in_array($tripType, ['morning', 'afternoon'], true)) {
        $errors[] = 'Select morning or afternoon.';
    }
    if (!in_array($trafficLevel, ['low', 'medium', 'high'], true)) {
        $errors[] = 'Select a valid traffic level.';
    }
    if (!in_array($weather, ['clear', 'rain', 'heavy_rain', 'fog'], true)) {
        $errors[] = 'Select a valid weather condition.';
    }
    if (!in_array($schoolPeriod, ['regular', 'exam', 'half_day'], true)) {
        $errors[] = 'Select a valid school schedule.';
    }
    if ($scenarioHour === false || $scenarioHour < 0 || $scenarioHour > 23) {
        $errors[] = 'Hour must be between 0 and 23.';
    }
    if ($scenarioDay === false || $scenarioDay < 0 || $scenarioDay > 6) {
        $errors[] = 'Select a valid day of week.';
    }

    $route = null;
    $routeStudents = [];
    if (!$errors) {
        $routeStatement = $pdo->prepare('SELECT * FROM routes WHERE id = :id AND active = 1');
        $routeStatement->execute(['id' => $routeId]);
        $route = $routeStatement->fetch() ?: null;
        if ($route === null) {
            $errors[] = 'The selected route is not available.';
        } else {
            $studentStatement = $pdo->prepare(
                'SELECT s.id, s.name, s.van_id, s.pickup_location,
                        s.pickup_lat, s.pickup_lng, rs.stop_sequence
                 FROM route_students rs
                 JOIN students s ON s.id = rs.student_id
                 WHERE rs.route_id = :route_id AND s.active = 1
                 ORDER BY rs.stop_sequence'
            );
            $studentStatement->execute(['route_id' => $routeId]);
            $routeStudents = $studentStatement->fetchAll();
            if (!$routeStudents) {
                $errors[] = 'Assign at least one active student stop to this route.';
            }
        }
    }

    if (!$errors && $route !== null) {
        $driver = $driversById[$driverId];
        foreach ($routeStudents as $student) {
            if ((int) $student['van_id'] !== (int) $driver['van_id']) {
                $errors[] = 'Every student on this route must be assigned to '
                    . $driver['van_number'] . '.';
                break;
            }
        }
    }

    if (!$errors && $route !== null) {
        $activeCheck = $pdo->prepare(
            "SELECT id FROM trips
             WHERE van_id = :van_id
               AND status IN ('scheduled','active','paused','emergency')
             LIMIT 1"
        );
        $activeCheck->execute(['van_id' => $driver['van_id']]);
        if ($activeCheck->fetch()) {
            $errors[] = 'This van already has a scheduled or active trip.';
        }
    }

    if (!$errors && $route !== null) {
        $orderedStudents = $tripType === 'morning'
            ? $routeStudents : array_reverse($routeStudents);
        $initialLat = $tripType === 'morning' ? $route['start_lat'] : $route['school_lat'];
        $initialLng = $tripType === 'morning' ? $route['start_lng'] : $route['school_lng'];
        $initialSpeed = min(25.0, (float) $driver['speed_limit_kmh']);
        try {
            $pdo->beginTransaction();
            $tripStatement = $pdo->prepare(
                'INSERT INTO trips (
                    route_id, van_id, driver_id, trip_type, status,
                    current_lat, current_lng, physical_speed_kmh,
                    playback_multiplier, random_seed,
                    scenario_traffic_level, scenario_weather,
                    scenario_school_period, scenario_hour_of_day,
                    scenario_day_of_week
                 ) VALUES (
                    :route_id, :van_id, :driver_id, :trip_type, \'scheduled\',
                    :current_lat, :current_lng, :physical_speed_kmh,
                    1, :random_seed, :traffic_level, :weather,
                    :school_period, :hour_of_day, :day_of_week
                 )'
            );
            $tripStatement->execute([
                'route_id' => $routeId,
                'van_id' => $driver['van_id'],
                'driver_id' => $driverId,
                'trip_type' => $tripType,
                'current_lat' => $initialLat,
                'current_lng' => $initialLng,
                'physical_speed_kmh' => $initialSpeed,
                'random_seed' => random_int(1, 2_147_483_647),
                'traffic_level' => $trafficLevel,
                'weather' => $weather,
                'school_period' => $schoolPeriod,
                'hour_of_day' => $scenarioHour,
                'day_of_week' => $scenarioDay,
            ]);
            $tripId = (int) $pdo->lastInsertId();
            $stopStatement = $pdo->prepare(
                'INSERT INTO trip_stops (
                    trip_id, student_id, stop_order, stop_name,
                    stop_lat, stop_lng, stop_type
                 ) VALUES (
                    :trip_id, :student_id, :stop_order, :stop_name,
                    :stop_lat, :stop_lng, :stop_type
                 )'
            );
            $order = 1;
            foreach ($orderedStudents as $student) {
                $stopStatement->execute([
                    'trip_id' => $tripId,
                    'student_id' => $student['id'],
                    'stop_order' => $order++,
                    'stop_name' => $student['name'] . ' — ' . $student['pickup_location'],
                    'stop_lat' => $student['pickup_lat'],
                    'stop_lng' => $student['pickup_lng'],
                    'stop_type' => 'student_home',
                ]);
            }
            $stopStatement->execute([
                'trip_id' => $tripId,
                'student_id' => null,
                'stop_order' => $order,
                'stop_name' => $tripType === 'morning'
                    ? $route['school_name'] : $route['start_name'],
                'stop_lat' => $tripType === 'morning'
                    ? $route['school_lat'] : $route['start_lat'],
                'stop_lng' => $tripType === 'morning'
                    ? $route['school_lng'] : $route['start_lng'],
                'stop_type' => $tripType === 'morning' ? 'school' : 'depot',
            ]);
            $pdo->commit();
            $assignmentMessage = $tripType === 'morning'
                ? ' Morning pickup attendance is not required.'
                : ' The driver must take attendance before starting.';
            set_flash('success', 'Trip #' . $tripId . ' assigned.' . $assignmentMessage);
            redirect('/admin/manage-trips.php');
        } catch (Throwable $exception) {
            if ($pdo->inTransaction()) $pdo->rollBack();
            $errors[] = 'The trip could not be created.';
        }
    }
}

$nepalNow = new DateTimeImmutable('now', new DateTimeZone('Asia/Kathmandu'));

render_header('Manage trips');
render_admin_navigation('trips');
?>
<div class="page-heading">
    <div>
        <span class="eyebrow">Administrator</span>
        <h1>Schedule trips</h1>
        <p>Create a morning or afternoon assignment. Morning trips start directly; afternoon trips require attendance.</p>
    </div>
    <div class="inline-actions">
        <a class="primary-button secondary-button"
           href="<?= APP_BASE_URL ?>/admin/trip-history.php">View trip history</a>
    </div>
</div>
<?php render_form_errors($errors); ?>
<section class="panel">
    <h2>Create driver assignment</h2>
    <form method="post" class="form-grid">
        <input type="hidden" name="csrf_token" value="<?= csrf_token() ?>">
        <label>Route
            <select name="route_id" required>
                <option value="">Select route</option>
                <?php foreach ($routes as $route): ?>
                    <option value="<?= (int) $route['id'] ?>"
                        <?= (int) $route['stop_count'] < 1 ? 'disabled' : '' ?>>
                        <?= escape($route['name']) ?> — <?= (int) $route['stop_count'] ?> students
                    </option>
                <?php endforeach; ?>
            </select>
        </label>
        <label>Driver and van
            <select name="driver_id" required>
                <option value="">Select driver</option>
                <?php foreach ($drivers as $driver): ?>
                    <option value="<?= (int) $driver['driver_id'] ?>">
                        <?= escape($driver['driver_name']) ?> — <?= escape($driver['van_number']) ?>
                    </option>
                <?php endforeach; ?>
            </select>
        </label>
        <label>Trip
            <select name="trip_type" required>
                <option value="morning">Morning: depot → homes → school</option>
                <option value="afternoon">Afternoon: school → homes → depot</option>
            </select>
        </label>
        <label>Traffic
            <select name="traffic_level"><option value="low">Low</option><option value="medium" selected>Medium</option><option value="high">Heavy</option></select>
        </label>
        <label>Weather
            <select name="weather"><option value="clear">Clear</option><option value="rain">Rain</option><option value="heavy_rain">Heavy rain</option><option value="fog">Fog</option></select>
        </label>
        <label>School schedule
            <select name="school_period"><option value="regular">Regular</option><option value="exam">Exam</option><option value="half_day">Half day</option></select>
        </label>
        <label>Departure hour
            <input name="hour_of_day" type="number" min="0" max="23" value="<?= (int) $nepalNow->format('G') ?>" required>
        </label>
        <label>Day
            <select name="day_of_week">
                <?php foreach (['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'] as $index => $day): ?>
                    <option value="<?= $index ?>" <?= $index === (int) $nepalNow->format('N') - 1 ? 'selected' : '' ?>><?= $day ?></option>
                <?php endforeach; ?>
            </select>
        </label>
        <div class="inline-actions"><button type="submit">Assign trip</button></div>
    </form>
</section>
<?php render_footer(); ?>
