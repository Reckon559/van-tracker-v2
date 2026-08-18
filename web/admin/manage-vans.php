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
    'id' => '',
    'van_number' => '',
    'plate_number' => '',
    'capacity' => '15',
    'speed_limit_kmh' => '40',
];

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    verify_csrf();
    $action = (string) ($_POST['action'] ?? '');

    if ($action === 'toggle') {
        $vanId = positive_int($_POST['van_id'] ?? null);
        if ($vanId !== null) {
            $statement = $pdo->prepare(
                'UPDATE vans SET active = IF(active = 1, 0, 1) WHERE id = :id'
            );
            $statement->execute(['id' => $vanId]);
            set_flash('success', 'Van status updated.');
        }
        redirect('/admin/manage-vans.php');
    }

    if ($action === 'save') {
        $form = [
            'id' => trim((string) ($_POST['van_id'] ?? '')),
            'van_number' => trim((string) ($_POST['van_number'] ?? '')),
            'plate_number' => strtoupper(trim((string) ($_POST['plate_number'] ?? ''))),
            'capacity' => trim((string) ($_POST['capacity'] ?? '')),
            'speed_limit_kmh' => trim((string) ($_POST['speed_limit_kmh'] ?? '')),
        ];
        $vanId = $form['id'] === '' ? null : positive_int($form['id']);
        $capacity = positive_int($form['capacity']);
        $speedLimit = is_numeric($form['speed_limit_kmh'])
            ? (float) $form['speed_limit_kmh']
            : null;

        if ($form['van_number'] === '') $errors[] = 'Van number is required.';
        if ($form['plate_number'] === '') $errors[] = 'Plate number is required.';
        if ($capacity === null || $capacity > 100) {
            $errors[] = 'Capacity must be between 1 and 100.';
        }
        if ($speedLimit === null || $speedLimit < 10 || $speedLimit > 100) {
            $errors[] = 'Speed limit must be between 10 and 100 km/h.';
        }

        if (!$errors) {
            try {
                if ($vanId === null) {
                    $statement = $pdo->prepare(
                        'INSERT INTO vans
                            (van_number, plate_number, capacity, speed_limit_kmh)
                         VALUES
                            (:van_number, :plate_number, :capacity, :speed_limit)'
                    );
                } else {
                    $statement = $pdo->prepare(
                        'UPDATE vans
                         SET van_number = :van_number,
                             plate_number = :plate_number,
                             capacity = :capacity,
                             speed_limit_kmh = :speed_limit
                         WHERE id = :id'
                    );
                }
                $parameters = [
                    'van_number' => $form['van_number'],
                    'plate_number' => $form['plate_number'],
                    'capacity' => $capacity,
                    'speed_limit' => $speedLimit,
                ];
                if ($vanId !== null) $parameters['id'] = $vanId;
                $statement->execute($parameters);
                set_flash('success', $vanId === null ? 'Van created.' : 'Van updated.');
                redirect('/admin/manage-vans.php');
            } catch (PDOException $exception) {
                if ((int) ($exception->errorInfo[1] ?? 0) === 1062) {
                    $errors[] = 'That van number or plate number already exists.';
                } else {
                    throw $exception;
                }
            }
        }
    }
}

$editId = positive_int($_GET['edit'] ?? null);
if ($_SERVER['REQUEST_METHOD'] !== 'POST' && $editId !== null) {
    $statement = $pdo->prepare('SELECT * FROM vans WHERE id = :id');
    $statement->execute(['id' => $editId]);
    if ($record = $statement->fetch()) {
        $form = [
            'id' => (string) $record['id'],
            'van_number' => $record['van_number'],
            'plate_number' => $record['plate_number'],
            'capacity' => (string) $record['capacity'],
            'speed_limit_kmh' => (string) $record['speed_limit_kmh'],
        ];
    }
}

$vans = $pdo->query(
    'SELECT v.*, u.name AS driver_name
     FROM vans v
     LEFT JOIN drivers d ON d.van_id = v.id
     LEFT JOIN users u ON u.id = d.user_id
     ORDER BY v.active DESC, v.van_number'
)->fetchAll();

render_header('Manage vans');
render_admin_navigation('vans');
?>
<div class="page-heading">
    <div>
        <span class="eyebrow">Administrator</span>
        <h1>Manage vans</h1>
        <p>Create the vehicles that will later run simulated trips.</p>
    </div>
</div>

<section class="panel">
    <h2><?= $form['id'] === '' ? 'Add van' : 'Edit van' ?></h2>
    <?php render_form_errors($errors); ?>
    <form method="post" class="form-grid">
        <input type="hidden" name="csrf_token" value="<?= csrf_token() ?>">
        <input type="hidden" name="action" value="save">
        <input type="hidden" name="van_id" value="<?= escape($form['id']) ?>">
        <label>
            Van number
            <input name="van_number" value="<?= escape($form['van_number']) ?>"
                   placeholder="VAN-03" required>
        </label>
        <label>
            Plate number
            <input name="plate_number" value="<?= escape($form['plate_number']) ?>"
                   placeholder="BA 2 KHA 1003" required>
        </label>
        <label>
            Student capacity
            <input type="number" name="capacity" min="1" max="100"
                   value="<?= escape($form['capacity']) ?>" required>
        </label>
        <label>
            Physical speed limit (km/h)
            <input type="number" name="speed_limit_kmh" min="10" max="100" step="0.1"
                   value="<?= escape($form['speed_limit_kmh']) ?>" required>
        </label>
        <div class="inline-actions full-width">
            <button type="submit"><?= $form['id'] === '' ? 'Add van' : 'Save changes' ?></button>
            <?php if ($form['id'] !== ''): ?>
                <a class="primary-button secondary-button" href="<?= APP_BASE_URL ?>/admin/manage-vans.php">Cancel</a>
            <?php endif; ?>
        </div>
    </form>
</section>

<section class="panel">
    <h2>All vans</h2>
    <div class="data-table-wrap">
        <table class="data-table">
            <thead>
            <tr>
                <th>Van</th>
                <th>Plate</th>
                <th>Capacity</th>
                <th>Limit</th>
                <th>Driver</th>
                <th>Status</th>
                <th>Actions</th>
            </tr>
            </thead>
            <tbody>
            <?php foreach ($vans as $van): ?>
                <tr>
                    <td><?= escape($van['van_number']) ?></td>
                    <td><?= escape($van['plate_number']) ?></td>
                    <td><?= (int) $van['capacity'] ?></td>
                    <td><?= escape((string) $van['speed_limit_kmh']) ?> km/h</td>
                    <td><?= escape($van['driver_name'] ?? 'Not assigned') ?></td>
                    <td>
                        <span class="status-badge <?= $van['active'] ? '' : 'inactive' ?>">
                            <?= $van['active'] ? 'Active' : 'Inactive' ?>
                        </span>
                    </td>
                    <td>
                        <div class="inline-actions">
                            <a class="primary-button small-button secondary-button"
                               href="?edit=<?= (int) $van['id'] ?>">Edit</a>
                            <form method="post">
                                <input type="hidden" name="csrf_token" value="<?= csrf_token() ?>">
                                <input type="hidden" name="action" value="toggle">
                                <input type="hidden" name="van_id" value="<?= (int) $van['id'] ?>">
                                <button class="small-button <?= $van['active'] ? 'danger-button' : '' ?>"
                                        type="submit">
                                    <?= $van['active'] ? 'Deactivate' : 'Activate' ?>
                                </button>
                            </form>
                        </div>
                    </td>
                </tr>
            <?php endforeach; ?>
            </tbody>
        </table>
    </div>
</section>
<?php render_footer(); ?>

