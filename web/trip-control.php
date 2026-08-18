<?php
declare(strict_types=1);

require_once __DIR__ . '/config/app.php';
require_once __DIR__ . '/config/database.php';
require_once __DIR__ . '/includes/auth.php';
require_once __DIR__ . '/includes/layout.php';
require_once __DIR__ . '/includes/trips.php';

require_role('driver');
$pdo = database();
$errors = [];

if ($_SESSION['user_role'] === 'admin') {
    $driverStatement = $pdo->query(
        'SELECT d.id AS driver_id, u.name AS driver_name,
                v.id AS van_id, v.van_number, v.speed_limit_kmh
         FROM drivers d
         JOIN users u ON u.id = d.user_id
         JOIN vans v ON v.id = d.van_id
         WHERE u.active = 1 AND v.active = 1
         ORDER BY u.name'
    );
} else {
    $driverStatement = $pdo->prepare(
        'SELECT d.id AS driver_id, u.name AS driver_name,
                v.id AS van_id, v.van_number, v.speed_limit_kmh
         FROM drivers d
         JOIN users u ON u.id = d.user_id
         JOIN vans v ON v.id = d.van_id
         WHERE d.user_id = :user_id AND u.active = 1 AND v.active = 1'
    );
    $driverStatement->execute(['user_id' => $_SESSION['user_id']]);
}
$availableDrivers = $driverStatement->fetchAll();
$allowedDriverIds = array_column($availableDrivers, null, 'driver_id');

$routes = $pdo->query(
    'SELECT r.*,
            (SELECT COUNT(*) FROM route_students rs WHERE rs.route_id = r.id) AS stop_count
     FROM routes r
     WHERE r.active = 1
     ORDER BY r.name'
)->fetchAll();

if (false && $_SERVER['REQUEST_METHOD'] === 'POST') {
    verify_csrf();
    $action = (string) ($_POST['action'] ?? '');

    if ($action === 'create_trip') {
        $routeId = positive_int($_POST['route_id'] ?? null);
        $driverId = positive_int($_POST['driver_id'] ?? null);
        $tripType = (string) ($_POST['trip_type'] ?? '');
        $trafficLevel = (string) ($_POST['traffic_level'] ?? 'medium');
        $weather = (string) ($_POST['weather'] ?? 'clear');
        $schoolPeriod = (string) ($_POST['school_period'] ?? 'regular');
        $scenarioHour = filter_var(
            $_POST['hour_of_day'] ?? null,
            FILTER_VALIDATE_INT
        );
        $scenarioDay = filter_var(
            $_POST['day_of_week'] ?? null,
            FILTER_VALIDATE_INT
        );

        if ($routeId === null) $errors[] = 'Select a route.';
        if ($driverId === null || !isset($allowedDriverIds[$driverId])) {
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
            $routeStatement = $pdo->prepare(
                'SELECT * FROM routes WHERE id = :id AND active = 1'
            );
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
            $driver = $allowedDriverIds[$driverId];
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
                ? $routeStudents
                : array_reverse($routeStudents);
            $initialLat = $tripType === 'morning'
                ? $route['start_lat']
                : $route['school_lat'];
            $initialLng = $tripType === 'morning'
                ? $route['start_lng']
                : $route['school_lng'];
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
                        :route_id, :van_id, :driver_id, :trip_type, :status,
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
                    'status' => 'scheduled',
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

                if ($tripType === 'morning') {
                    $finalName = $route['school_name'];
                    $finalLat = $route['school_lat'];
                    $finalLng = $route['school_lng'];
                    $finalType = 'school';
                } else {
                    $finalName = $route['start_name'];
                    $finalLat = $route['start_lat'];
                    $finalLng = $route['start_lng'];
                    $finalType = 'depot';
                }
                $stopStatement->execute([
                    'trip_id' => $tripId,
                    'student_id' => null,
                    'stop_order' => $order,
                    'stop_name' => $finalName,
                    'stop_lat' => $finalLat,
                    'stop_lng' => $finalLng,
                    'stop_type' => $finalType,
                ]);

                $pdo->commit();
                set_flash('success', 'Trip created. Initialize the A* route, then start the simulation.');
                redirect('/trip-control.php?trip_id=' . $tripId);
            } catch (Throwable $exception) {
                if ($pdo->inTransaction()) $pdo->rollBack();
                $errors[] = 'The trip could not be created.';
            }
        }
    }
}

if ($_SESSION['user_role'] === 'admin') {
    $tripListStatement = $pdo->query(
        'SELECT t.id, t.trip_type, t.status, t.created_at,
                r.name AS route_name, v.van_number
         FROM trips t
         JOIN routes r ON r.id = t.route_id
         JOIN vans v ON v.id = t.van_id
         ORDER BY t.id DESC LIMIT 30'
    );
} else {
    $tripListStatement = $pdo->prepare(
        'SELECT t.id, t.trip_type, t.status, t.created_at,
                r.name AS route_name, v.van_number
         FROM trips t
         JOIN routes r ON r.id = t.route_id
         JOIN vans v ON v.id = t.van_id
         JOIN drivers d ON d.id = t.driver_id
         WHERE d.user_id = :user_id
         ORDER BY t.id DESC LIMIT 30'
    );
    $tripListStatement->execute(['user_id' => $_SESSION['user_id']]);
}
$trips = $tripListStatement->fetchAll();

$tripId = positive_int($_GET['trip_id'] ?? null);
if ($tripId === null && $trips) $tripId = (int) $trips[0]['id'];
$trip = null;
$tripStops = [];
$routePoints = [];
$stopNames = [];
$stopContexts = [];
$activeStopOrders = [];
$attendanceComplete = false;
$attendanceRequired = false;
$studentTripStops = [];
$lastSavedSample = -1;

if ($tripId !== null && find_accessible_trip($pdo, $tripId) !== null) {
    $tripStatement = $pdo->prepare(
        'SELECT t.*, r.name AS route_name, r.start_name, r.start_lat, r.start_lng,
                r.school_name, r.school_lat, r.school_lng,
                v.van_number, v.plate_number, v.speed_limit_kmh,
                u.name AS driver_name
         FROM trips t
         JOIN routes r ON r.id = t.route_id
         JOIN vans v ON v.id = t.van_id
         JOIN drivers d ON d.id = t.driver_id
         JOIN users u ON u.id = d.user_id
         WHERE t.id = :trip_id'
    );
    $tripStatement->execute(['trip_id' => $tripId]);
    $trip = $tripStatement->fetch() ?: null;

    if ($trip !== null) {
        $attendanceRequired = $trip['trip_type'] === 'afternoon';
        $stopStatement = $pdo->prepare(
            'SELECT * FROM trip_stops
             WHERE trip_id = :trip_id ORDER BY stop_order'
        );
        $stopStatement->execute(['trip_id' => $tripId]);
        $tripStops = $stopStatement->fetchAll();
        $studentTripStops = array_values(array_filter(
            $tripStops,
            static fn(array $stop): bool => $stop['student_id'] !== null
        ));

        if ($_SERVER['REQUEST_METHOD'] === 'POST'
            && ($_POST['action'] ?? '') === 'save_attendance') {
            verify_csrf();
            if (!$attendanceRequired) {
                $errors[] = 'Attendance is not used for morning pickup trips.';
            }
            if ($trip['status'] !== 'scheduled') {
                $errors[] = 'Attendance can only be changed before the trip starts.';
            }
            $submitted = is_array($_POST['attendance'] ?? null)
                ? $_POST['attendance'] : [];
            $attendanceValues = [];
            foreach ($studentTripStops as $studentStop) {
                $stopId = (int) $studentStop['id'];
                $value = (string) ($submitted[$stopId] ?? '');
                if (!in_array($value, ['present', 'absent'], true)) {
                    $errors[] = 'Mark every student present or absent.';
                    break;
                }
                $attendanceValues[$stopId] = $value;
            }
            if (!$errors) {
                try {
                    $pdo->beginTransaction();
                    $attendanceUpdate = $pdo->prepare(
                        "UPDATE trip_stops
                         SET attendance_status = :attendance_status,
                             attendance_marked_at = NOW(),
                             attendance_marked_by = :marked_by,
                             status = :stop_status,
                             arrived_at = NULL,
                             route_distance_m = NULL
                         WHERE id = :stop_id
                           AND trip_id = :trip_id
                           AND student_id IS NOT NULL"
                    );
                    foreach ($attendanceValues as $stopId => $value) {
                        $attendanceUpdate->execute([
                            'attendance_status' => $value,
                            'marked_by' => (int) $_SESSION['user_id'],
                            'stop_status' => $value === 'present' ? 'pending' : 'skipped',
                            'stop_id' => $stopId,
                            'trip_id' => $tripId,
                        ]);
                    }
                    $pdo->commit();
                    set_flash('success', 'Attendance saved. The route keeps every home point for map tracking; absent students receive no ETA or arrival status.');
                    redirect('/trip-control.php?trip_id=' . $tripId);
                } catch (Throwable $exception) {
                    if ($pdo->inTransaction()) $pdo->rollBack();
                    $errors[] = 'Attendance could not be saved.';
                }
            }
        }

        $attendanceComplete = !$attendanceRequired || (
            count($studentTripStops) > 0
            && count(array_filter(
                $studentTripStops,
                static fn(array $stop): bool => in_array(
                    $stop['attendance_status'], ['present', 'absent'], true
                )
            )) === count($studentTripStops)
        );

        if ($trip['trip_type'] === 'morning') {
            $routePoints[] = [
                'lat' => (float) $trip['start_lat'],
                'lng' => (float) $trip['start_lng'],
            ];
            $stopNames[] = $trip['start_name'];
            $stopContexts[] = 'depot';
        } else {
            $routePoints[] = [
                'lat' => (float) $trip['school_lat'],
                'lng' => (float) $trip['school_lng'],
            ];
            $stopNames[] = $trip['school_name'];
            $stopContexts[] = 'school';
        }
        foreach ($tripStops as $stop) {
            if ($attendanceRequired
                && $stop['student_id'] !== null
                && $stop['attendance_status'] === 'unmarked') {
                continue;
            }
            $routePoints[] = [
                'lat' => (float) $stop['stop_lat'],
                'lng' => (float) $stop['stop_lng'],
            ];
            $stopNames[] = $stop['stop_name'];
            $stopContexts[] = match ($stop['stop_type']) {
                'school' => 'school',
                'depot' => 'depot',
                'student_home' => 'bus_stop',
                default => 'unknown',
            };
            $activeStopOrders[] = (int) $stop['stop_order'];
        }

        $sampleStatement = $pdo->prepare(
            'SELECT COALESCE(MAX(sample_index), -1)
             FROM trip_telemetry WHERE trip_id = :trip_id'
        );
        $sampleStatement->execute(['trip_id' => $tripId]);
        $lastSavedSample = (int) $sampleStatement->fetchColumn();
    }
}

render_header('Driver trip control');
render_driver_navigation('control');
?>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<div class="page-heading">
    <div>
        <span class="eyebrow">Driver</span>
        <h1>Assigned trip control</h1>
    </div>
</div>

<?php render_form_errors($errors); ?>

<?php if (false): ?>
<section class="panel">
    <h2>Create trip</h2>
    <form method="post" class="form-grid">
        <input type="hidden" name="csrf_token" value="<?= csrf_token() ?>">
        <input type="hidden" name="action" value="create_trip">
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
                <?php foreach ($availableDrivers as $driver): ?>
                    <option value="<?= (int) $driver['driver_id'] ?>">
                        <?= escape($driver['driver_name']) ?> — <?= escape($driver['van_number']) ?>
                    </option>
                <?php endforeach; ?>
            </select>
        </label>
        <label>Trip direction
            <select name="trip_type" required>
                <option value="morning">Morning: depot → homes → school</option>
                <option value="afternoon">Afternoon: school → homes → depot</option>
            </select>
        </label>
        <?php
        $nepalNow = new DateTimeImmutable('now', new DateTimeZone('Asia/Kathmandu'));
        ?>
        <label>Traffic scenario
            <select name="traffic_level" required>
                <option value="low">Low traffic</option>
                <option value="medium" selected>Medium traffic</option>
                <option value="high">Heavy traffic</option>
            </select>
        </label>
        <label>Weather
            <select name="weather" required>
                <option value="clear" selected>Clear</option>
                <option value="rain">Rain</option>
                <option value="heavy_rain">Heavy rain</option>
                <option value="fog">Fog</option>
            </select>
        </label>
        <label>School schedule
            <select name="school_period" required>
                <option value="regular" selected>Regular day</option>
                <option value="exam">Exam period</option>
                <option value="half_day">Half-day leave</option>
            </select>
        </label>
        <label>Departure hour (0–23)
            <input name="hour_of_day" type="number" min="0" max="23"
                   value="<?= (int) $nepalNow->format('G') ?>" required>
        </label>
        <label>Day of week
            <select name="day_of_week" required>
                <?php
                $dayNames = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
                $todayIndex = (int) $nepalNow->format('N') - 1;
                foreach ($dayNames as $dayIndex => $dayName):
                ?>
                    <option value="<?= $dayIndex ?>" <?= $dayIndex === $todayIndex ? 'selected' : '' ?>>
                        <?= $dayName ?>
                    </option>
                <?php endforeach; ?>
            </select>
        </label>
        <div class="inline-actions">
            <button type="submit">Create scheduled trip</button>
        </div>
    </form>
</section>
<?php endif; ?>

<?php if ($trip !== null): ?>
    <?php if ($attendanceRequired): ?>
    <section class="panel attendance-panel">
        <div class="simulation-status-row">
            <div>
                <span class="panel-kicker">Required before Start</span>
                <h2>Student attendance</h2>
                <p class="muted">Absent students are excluded from this trip’s A* route and cannot receive an arrival event.</p>
            </div>
            <span class="status-badge <?= $attendanceComplete ? 'status-active' : 'status-paused' ?>">
                <?= $attendanceComplete ? 'Complete' : 'Required' ?>
            </span>
        </div>
        <?php if ($trip['status'] === 'scheduled'): ?>
            <form method="post" class="attendance-form">
                <input type="hidden" name="csrf_token" value="<?= csrf_token() ?>">
                <input type="hidden" name="action" value="save_attendance">
                <div class="attendance-list">
                    <?php foreach ($studentTripStops as $studentStop): ?>
                        <fieldset class="attendance-row">
                            <legend><?= escape($studentStop['stop_name']) ?></legend>
                            <label><input type="radio"
                                name="attendance[<?= (int) $studentStop['id'] ?>]"
                                value="present"
                                <?= $studentStop['attendance_status'] === 'present' ? 'checked' : '' ?> required> Present</label>
                            <label><input type="radio"
                                name="attendance[<?= (int) $studentStop['id'] ?>]"
                                value="absent"
                                <?= $studentStop['attendance_status'] === 'absent' ? 'checked' : '' ?> required> Absent</label>
                        </fieldset>
                    <?php endforeach; ?>
                </div>
                <button type="submit">Save attendance</button>
            </form>
        <?php else: ?>
            <div class="attendance-list">
                <?php foreach ($studentTripStops as $studentStop): ?>
                    <div class="attendance-row">
                        <strong><?= escape($studentStop['stop_name']) ?></strong>
                        <span><?= escape(ucfirst($studentStop['attendance_status'])) ?></span>
                    </div>
                <?php endforeach; ?>
            </div>
        <?php endif; ?>
    </section>
    <?php endif; ?>

    <section class="metric-grid simulation-metrics">
        <?php
        status_card('Trip', '#' . $trip['id'] . ' · ' . ucfirst($trip['trip_type']), $trip['route_name']);
        status_card('Van', $trip['van_number'], $trip['driver_name']);
        status_card('Physical limit', $trip['speed_limit_kmh'] . ' km/h');
        status_card('Saved telemetry', max(0, $lastSavedSample + 1) . ' rows');
        ?>
    </section>

    <section class="simulation-layout">
        <aside class="panel simulation-controls">
            <div class="simulation-status-row">
                <div>
                    <h2>Controls</h2>
                </div>
                <span id="simulation-status" class="status-badge">Initializing</span>
            </div>
            <div id="simulation-error" class="alert alert-danger" hidden></div>

            <div class="control-button-grid">
                <button id="start-trip">Start</button>
                <button id="pause-trip" class="warning-button">Start long stop</button>
                <button id="resume-trip" class="secondary-button">Resume</button>
                <button id="emergency-trip" class="danger-button">Emergency stop</button>
            </div>

            <label>Stop location context
                <select id="stop-context">
                    <option value="auto" selected>Automatic detector (prototype)</option>
                    <option value="unknown">Unknown roadside</option>
                    <option value="traffic_light">Traffic light</option>
                    <option value="bus_stop">Bus stop</option>
                    <option value="school">School</option>
                    <option value="depot">Depot</option>
                </select>
            </label>
            <button id="toggle-context-radius" type="button"
                    class="secondary-button" disabled>
                Show all context radii
            </button>

            <div class="obstacle-demo-box">
                <div>
                    <strong>Road obstacle</strong>
                </div>
                <label>Obstacle ahead (m)
                    <input id="obstacle-distance" type="number" min="30" max="2000"
                           step="10" value="150">
                </label>
                <button id="add-obstacle" type="button" class="warning-button">
                    Add road obstacle
                </button>
            </div>

            <div class="anomaly-demo-box">
                <div>
                    <strong>Route deviation</strong>
                </div>
                <label>Tentative deviation distance (m)
                    <input id="deviation-distance" type="number" min="20" max="2000"
                           step="10" value="400">
                </label>
                <label>Deviation direction
                    <select id="deviation-direction">
                        <option value="0">North (0°)</option>
                        <option value="45">North-east (45°)</option>
                        <option value="90" selected>East (90°)</option>
                        <option value="135">South-east (135°)</option>
                        <option value="180">South (180°)</option>
                        <option value="225">South-west (225°)</option>
                        <option value="270">West (270°)</option>
                        <option value="315">North-west (315°)</option>
                        <option value="custom">Custom degree</option>
                    </select>
                </label>
                <label>Direction degree
                    <input id="deviation-bearing" type="number" min="0" max="359"
                           step="1" value="90">
                </label>
                <div class="control-button-grid compact-grid">
                    <button id="start-deviation" type="button" class="warning-button">
                        Deviate route
                    </button>
                    <button id="return-route" type="button" class="secondary-button">
                        Return to route
                    </button>
                </div>
            </div>

            <label>Physical van speed (km/h)
                <div class="input-action-row">
                    <input id="physical-speed" type="number" min="0" max="150" step="1"
                           value="<?= escape((string) $trip['physical_speed_kmh']) ?>">
                    <button id="apply-speed" type="button">Apply</button>
                </div>
            </label>
            <div id="overspeed-warning" class="alert alert-danger" hidden>
                Physical speed is above this van’s configured limit.
            </div>

            <label>Playback speed
                <select id="playback-speed">
                    <option value="1">1× real-time display</option>
                    <option value="5">5× faster display</option>
                    <option value="10">10× faster display</option>
                </select>
            </label>

            <dl class="route-results">
                <div><dt>Simulated time</dt><dd id="simulated-time">0 sec</dd></div>
                <div><dt>Physical speed</dt><dd id="current-speed">0 km/h</dd></div>
                <div><dt>Travelled</dt><dd id="travelled-distance">0 km</dd></div>
                <div><dt>Remaining</dt><dd id="remaining-distance">—</dd></div>
                <div><dt>Road-segment baseline ETA</dt><dd id="baseline-eta">—</dd></div>
                <div class="eta-highlight"><dt>RF predicted ETA</dt><dd id="rf-eta">—</dd></div>
                <div><dt>Prediction range</dt><dd id="rf-eta-range">—</dd></div>
                <div><dt>ETA method</dt><dd id="eta-method">Loading model…</dd></div>
                <div><dt>Next stop</dt><dd id="next-stop">—</dd></div>
                <div><dt>Telemetry saved</dt><dd id="telemetry-count"><?= max(0, $lastSavedSample + 1) ?></dd></div>
                <div><dt>Hybrid status</dt><dd id="anomaly-status">Normal</dd></div>
                <div><dt>Isolation Forest</dt><dd id="if-status">Loading…</dd></div>
                <div><dt>Distance off-route</dt><dd id="deviation-metric">0 m</dd></div>
                <div><dt>Road event</dt><dd id="deviation-navigation">—</dd></div>
                <div><dt>Stop duration</dt><dd id="stop-duration">0 sec</dd></div>
                <div><dt>Location context type</dt><dd id="context-type">—</dd></div>
                <div><dt>Stopped at</dt><dd id="stop-location">—</dd></div>
            </dl>
            <p id="anomaly-reason" class="muted anomaly-reason"></p>
            <div class="scenario-strip" aria-label="ETA scenario">
                <span><?= escape(ucfirst($trip['scenario_traffic_level'])) ?> traffic</span>
                <span><?= escape(str_replace('_', ' ', ucfirst($trip['scenario_weather']))) ?></span>
                <span><?= escape(str_replace('_', ' ', ucfirst($trip['scenario_school_period']))) ?></span>
                <span><?= sprintf('%02d:00', (int) $trip['scenario_hour_of_day']) ?></span>
            </div>
            <div class="progress">
                <div id="simulation-progress" class="progress-bar"></div>
            </div>
        </aside>

        <section class="panel map-panel">
            <div id="simulation-map"></div>
        </section>
    </section>

    <div id="driver-notification-toasts" class="parent-safety-toasts"
         aria-live="polite"></div>

    <script>
    window.VAN_TRACKER_SIMULATION = <?= json_encode([
        'tripId' => (int) $trip['id'],
        'databaseStatus' => $trip['status'],
        'routingUrl' => ROUTING_SERVICE_URL,
        'syncUrl' => APP_BASE_URL . '/api/simulation-sync.php',
        'eventUrl' => APP_BASE_URL . '/api/simulation-event.php',
        'csrfToken' => csrf_token(),
        'points' => $routePoints,
        'stopNames' => $stopNames,
        'stopContexts' => $stopContexts,
        'activeStopOrders' => $activeStopOrders,
        'attendanceRequired' => $attendanceRequired,
        'attendanceComplete' => $attendanceComplete,
        'physicalSpeedKmh' => (float) $trip['physical_speed_kmh'],
        'speedLimitKmh' => (float) $trip['speed_limit_kmh'],
        'lastSavedSample' => $lastSavedSample,
        'trafficLevel' => $trip['scenario_traffic_level'],
        'weather' => $trip['scenario_weather'],
        'schoolPeriod' => $trip['scenario_school_period'],
        'hourOfDay' => (int) $trip['scenario_hour_of_day'],
        'dayOfWeek' => (int) $trip['scenario_day_of_week'],
    ], JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE) ?>;
    window.VAN_TRACKER_DRIVER_NOTIFICATIONS = <?= json_encode([
        'apiUrl' => APP_BASE_URL . '/api/driver-notifications.php',
        'viewerId' => (int) $_SESSION['user_id'],
        'surface' => 'trip_control',
    ], JSON_UNESCAPED_SLASHES) ?>;
    </script>
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <script src="<?= APP_BASE_URL ?>/assets/js/live-route.js?v=16"></script>
    <script src="<?= APP_BASE_URL ?>/assets/js/trip-control.js?v=16"></script>
    <script src="<?= APP_BASE_URL ?>/assets/js/driver-notifications.js?v=16"></script>
<?php endif; ?>
<?php render_footer(); ?>
