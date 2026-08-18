<?php
declare(strict_types=1);

require_once dirname(__DIR__) . '/config/app.php';
require_once dirname(__DIR__) . '/config/database.php';
require_once dirname(__DIR__) . '/includes/auth.php';
require_once dirname(__DIR__) . '/includes/layout.php';

require_role('driver');
$statement = database()->prepare(
    'SELECT t.id, t.trip_type, t.status, t.created_at,
            t.started_at, t.completed_at, t.simulated_elapsed_sec,
            r.name AS route_name, v.van_number, v.plate_number,
            SUM(ts.student_id IS NOT NULL) AS student_count,
            SUM(ts.student_id IS NOT NULL AND ts.attendance_status = \'present\') AS present_count,
            SUM(ts.student_id IS NOT NULL AND ts.attendance_status = \'absent\') AS absent_count,
            SUM(ts.student_id IS NOT NULL AND ts.attendance_status = \'unmarked\') AS unmarked_count
     FROM trips t
     JOIN drivers d ON d.id = t.driver_id
     JOIN routes r ON r.id = t.route_id
     JOIN vans v ON v.id = t.van_id
     LEFT JOIN trip_stops ts ON ts.trip_id = t.id
     WHERE d.user_id = :user_id
     GROUP BY t.id
     ORDER BY t.id DESC'
);
$statement->execute(['user_id' => $_SESSION['user_id']]);
$trips = $statement->fetchAll();

function format_driver_trip_duration(int $seconds): string
{
    if ($seconds <= 0) return '—';
    $hours = intdiv($seconds, 3600);
    $minutes = intdiv($seconds % 3600, 60);
    return $hours > 0
        ? sprintf('%d hr %d min', $hours, $minutes)
        : sprintf('%d min', max(1, $minutes));
}

function format_driver_trip_timestamp(?string $value): string
{
    return $value ? date('M d, Y · H:i', strtotime($value)) : '—';
}

render_header('Driver trip history');
render_driver_navigation('history');
?>
<div class="page-heading">
    <div><span class="eyebrow">Driver</span><h1>Trip history</h1></div>
    <a class="primary-button" href="<?= APP_BASE_URL ?>/driver/dashboard.php">Back to dashboard</a>
</div>
<section class="panel">
    <?php if (!$trips): ?><p class="muted">No trip records.</p><?php else: ?>
        <div class="history-toolbar">
            <label>
                <span>Search trips</span>
                <input id="trip-history-search" type="search"
                       placeholder="Route, van or trip number">
            </label>
            <label>
                <span>Status</span>
                <select id="trip-history-status">
                    <option value="">All statuses</option>
                    <option value="scheduled">Scheduled</option>
                    <option value="active">Active</option>
                    <option value="paused">Paused</option>
                    <option value="emergency">Emergency</option>
                    <option value="completed">Completed</option>
                    <option value="cancelled">Cancelled</option>
                </select>
            </label>
            <strong id="trip-history-count"><?= count($trips) ?> trips</strong>
        </div>
        <div class="data-table-wrap history-table-wrap"><table class="data-table history-table">
            <thead><tr><th>Trip</th><th>Route</th><th>Vehicle</th><th>Status</th><th>Attendance</th><th>Duration</th><th>Timeline</th><th>Action</th></tr></thead>
            <tbody><?php foreach ($trips as $trip): ?>
                <tr data-trip-history-row
                    data-status="<?= escape($trip['status']) ?>"
                    data-search="<?= escape(strtolower(implode(' ', [
                        '#' . $trip['id'], $trip['trip_type'], $trip['route_name'],
                        $trip['van_number'], $trip['plate_number'],
                    ]))) ?>">
                    <td><strong>#<?= (int) $trip['id'] ?></strong><br><small><?= escape(ucfirst($trip['trip_type'])) ?></small></td>
                    <td><strong><?= escape($trip['route_name']) ?></strong><br><small><?= (int) $trip['student_count'] ?> student stops</small></td>
                    <td><?= escape($trip['van_number']) ?><br><small><?= escape($trip['plate_number']) ?></small></td>
                    <td><span class="status-badge status-<?= escape($trip['status']) ?>"><?= escape(ucfirst($trip['status'])) ?></span></td>
                    <td>
                        <?php if ($trip['trip_type'] === 'morning'): ?>
                            Not required
                        <?php else: ?>
                            <?= (int) $trip['present_count'] ?> present · <?= (int) $trip['absent_count'] ?> absent
                            <?php if ((int) $trip['unmarked_count'] > 0): ?><br><small><?= (int) $trip['unmarked_count'] ?> unmarked</small><?php endif; ?>
                        <?php endif; ?>
                    </td>
                    <td><?= escape(format_driver_trip_duration((int) $trip['simulated_elapsed_sec'])) ?></td>
                    <td class="history-timeline">
                        <span>Created: <?= escape(format_driver_trip_timestamp($trip['created_at'])) ?></span>
                        <span>Started: <?= escape(format_driver_trip_timestamp($trip['started_at'])) ?></span>
                        <span>Finished: <?= escape(format_driver_trip_timestamp($trip['completed_at'])) ?></span>
                    </td>
                    <td><a class="primary-button small-button secondary-button"
                           href="<?= APP_BASE_URL ?>/trip-control.php?trip_id=<?= (int) $trip['id'] ?>">View</a></td>
                </tr>
            <?php endforeach; ?></tbody>
        </table></div>
        <p id="trip-history-empty" class="muted" hidden>No trips match these filters.</p>
    <?php endif; ?>
</section>
<script src="<?= APP_BASE_URL ?>/assets/js/trip-history.js?v=16"></script>
<?php render_footer(); ?>
