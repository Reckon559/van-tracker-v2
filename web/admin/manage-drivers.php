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
    'driver_id' => '',
    'name' => '',
    'email' => '',
    'phone' => '',
    'license_number' => '',
    'van_id' => '',
];

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    verify_csrf();
    $action = (string) ($_POST['action'] ?? '');

    if ($action === 'toggle') {
        $driverId = positive_int($_POST['driver_id'] ?? null);
        if ($driverId !== null) {
            $statement = $pdo->prepare(
                'UPDATE users u
                 JOIN drivers d ON d.user_id = u.id
                 SET u.active = IF(u.active = 1, 0, 1)
                 WHERE d.id = :driver_id'
            );
            $statement->execute(['driver_id' => $driverId]);
            set_flash('success', 'Driver status updated.');
        }
        redirect('/admin/manage-drivers.php');
    }

    if ($action === 'save') {
        $form = [
            'driver_id' => trim((string) ($_POST['driver_id'] ?? '')),
            'name' => trim((string) ($_POST['name'] ?? '')),
            'email' => strtolower(trim((string) ($_POST['email'] ?? ''))),
            'phone' => trim((string) ($_POST['phone'] ?? '')),
            'license_number' => trim((string) ($_POST['license_number'] ?? '')),
            'van_id' => trim((string) ($_POST['van_id'] ?? '')),
        ];
        $password = (string) ($_POST['password'] ?? '');
        $driverId = $form['driver_id'] === '' ? null : positive_int($form['driver_id']);
        $vanId = $form['van_id'] === '' ? null : positive_int($form['van_id']);

        if ($form['name'] === '') $errors[] = 'Driver name is required.';
        if (!filter_var($form['email'], FILTER_VALIDATE_EMAIL)) {
            $errors[] = 'Enter a valid driver email.';
        }
        if ($form['phone'] === '') $errors[] = 'Driver phone is required.';
        if ($driverId === null && strlen($password) < 8) {
            $errors[] = 'A new driver password must contain at least eight characters.';
        }

        if (!$errors) {
            try {
                $pdo->beginTransaction();
                if ($driverId === null) {
                    $userStatement = $pdo->prepare(
                        'INSERT INTO users (name, email, password_hash, role)
                         VALUES (:name, :email, :password_hash, :role)'
                    );
                    $userStatement->execute([
                        'name' => $form['name'],
                        'email' => $form['email'],
                        'password_hash' => password_hash($password, PASSWORD_DEFAULT),
                        'role' => 'driver',
                    ]);
                    $userId = (int) $pdo->lastInsertId();
                    $driverStatement = $pdo->prepare(
                        'INSERT INTO drivers (user_id, van_id, phone, license_number)
                         VALUES (:user_id, :van_id, :phone, :license_number)'
                    );
                    $driverStatement->execute([
                        'user_id' => $userId,
                        'van_id' => $vanId,
                        'phone' => $form['phone'],
                        'license_number' => $form['license_number'] ?: null,
                    ]);
                } else {
                    $driverStatement = $pdo->prepare(
                        'SELECT user_id FROM drivers WHERE id = :id FOR UPDATE'
                    );
                    $driverStatement->execute(['id' => $driverId]);
                    $record = $driverStatement->fetch();
                    if (!$record) throw new RuntimeException('Driver not found.');

                    $userStatement = $pdo->prepare(
                        'UPDATE users SET name = :name, email = :email WHERE id = :id'
                    );
                    $userStatement->execute([
                        'name' => $form['name'],
                        'email' => $form['email'],
                        'id' => $record['user_id'],
                    ]);
                    $driverStatement = $pdo->prepare(
                        'UPDATE drivers
                         SET van_id = :van_id, phone = :phone,
                             license_number = :license_number
                         WHERE id = :id'
                    );
                    $driverStatement->execute([
                        'van_id' => $vanId,
                        'phone' => $form['phone'],
                        'license_number' => $form['license_number'] ?: null,
                        'id' => $driverId,
                    ]);
                }
                $pdo->commit();
                set_flash('success', $driverId === null ? 'Driver account created.' : 'Driver updated.');
                redirect('/admin/manage-drivers.php');
            } catch (Throwable $exception) {
                if ($pdo->inTransaction()) $pdo->rollBack();
                if ($exception instanceof PDOException
                    && (int) ($exception->errorInfo[1] ?? 0) === 1062) {
                    $errors[] = 'That email or van assignment is already in use.';
                } else {
                    $errors[] = $exception->getMessage();
                }
            }
        }
    }
}

$editId = positive_int($_GET['edit'] ?? null);
if ($_SERVER['REQUEST_METHOD'] !== 'POST' && $editId !== null) {
    $statement = $pdo->prepare(
        'SELECT d.id AS driver_id, d.phone, d.license_number, d.van_id,
                u.name, u.email
         FROM drivers d JOIN users u ON u.id = d.user_id
         WHERE d.id = :id'
    );
    $statement->execute(['id' => $editId]);
    if ($record = $statement->fetch()) {
        $form = array_map(
            static fn ($value) => $value === null ? '' : (string) $value,
            $record
        );
    }
}

$vans = $pdo->query(
    'SELECT v.id, v.van_number, d.id AS assigned_driver_id
     FROM vans v
     LEFT JOIN drivers d ON d.van_id = v.id
     WHERE v.active = 1
     ORDER BY v.van_number'
)->fetchAll();

$drivers = $pdo->query(
    'SELECT d.id, d.phone, d.license_number, u.name, u.email, u.active,
            v.van_number, v.plate_number
     FROM drivers d
     JOIN users u ON u.id = d.user_id
     LEFT JOIN vans v ON v.id = d.van_id
     ORDER BY u.active DESC, u.name'
)->fetchAll();

render_header('Manage drivers');
render_admin_navigation('drivers');
?>
<div class="page-heading">
    <div>
        <span class="eyebrow">Administrator</span>
        <h1>Manage drivers</h1>
        <p>Create secure driver accounts and assign one driver per van.</p>
    </div>
</div>

<section class="panel">
    <h2><?= $form['driver_id'] === '' ? 'Add driver' : 'Edit driver' ?></h2>
    <?php render_form_errors($errors); ?>
    <form method="post" class="form-grid">
        <input type="hidden" name="csrf_token" value="<?= csrf_token() ?>">
        <input type="hidden" name="action" value="save">
        <input type="hidden" name="driver_id" value="<?= escape($form['driver_id']) ?>">
        <label>Driver name
            <input name="name" value="<?= escape($form['name']) ?>" required>
        </label>
        <label>Email
            <input type="email" name="email" value="<?= escape($form['email']) ?>" required>
        </label>
        <?php if ($form['driver_id'] === ''): ?>
            <label>Initial password
                <input type="password" name="password" minlength="8" required>
            </label>
        <?php endif; ?>
        <label>Phone
            <input name="phone" value="<?= escape($form['phone']) ?>" required>
        </label>
        <label>Licence number
            <input name="license_number" value="<?= escape($form['license_number']) ?>">
        </label>
        <label>Assign van
            <select name="van_id">
                <option value="">Not assigned</option>
                <?php foreach ($vans as $van): ?>
                    <?php
                    $available = $van['assigned_driver_id'] === null
                        || (int) $van['assigned_driver_id'] === (int) ($form['driver_id'] ?: 0);
                    if (!$available) continue;
                    ?>
                    <option value="<?= (int) $van['id'] ?>"
                        <?= (string) $van['id'] === $form['van_id'] ? 'selected' : '' ?>>
                        <?= escape($van['van_number']) ?>
                    </option>
                <?php endforeach; ?>
            </select>
        </label>
        <div class="inline-actions full-width">
            <button type="submit"><?= $form['driver_id'] === '' ? 'Create driver' : 'Save changes' ?></button>
            <?php if ($form['driver_id'] !== ''): ?>
                <a class="primary-button secondary-button" href="<?= APP_BASE_URL ?>/admin/manage-drivers.php">Cancel</a>
            <?php endif; ?>
        </div>
    </form>
</section>

<section class="panel">
    <h2>All drivers</h2>
    <div class="data-table-wrap">
        <table class="data-table">
            <thead><tr>
                <th>Driver</th><th>Contact</th><th>Van</th><th>Licence</th>
                <th>Status</th><th>Actions</th>
            </tr></thead>
            <tbody>
            <?php foreach ($drivers as $driver): ?>
                <tr>
                    <td><?= escape($driver['name']) ?><br><small><?= escape($driver['email']) ?></small></td>
                    <td><?= escape($driver['phone']) ?></td>
                    <td><?= escape($driver['van_number'] ?? 'Not assigned') ?></td>
                    <td><?= escape($driver['license_number'] ?? '—') ?></td>
                    <td><span class="status-badge <?= $driver['active'] ? '' : 'inactive' ?>">
                        <?= $driver['active'] ? 'Active' : 'Inactive' ?>
                    </span></td>
                    <td><div class="inline-actions">
                        <a class="primary-button small-button secondary-button"
                           href="?edit=<?= (int) $driver['id'] ?>">Edit</a>
                        <form method="post">
                            <input type="hidden" name="csrf_token" value="<?= csrf_token() ?>">
                            <input type="hidden" name="action" value="toggle">
                            <input type="hidden" name="driver_id" value="<?= (int) $driver['id'] ?>">
                            <button class="small-button <?= $driver['active'] ? 'danger-button' : '' ?>">
                                <?= $driver['active'] ? 'Deactivate' : 'Activate' ?>
                            </button>
                        </form>
                    </div></td>
                </tr>
            <?php endforeach; ?>
            </tbody>
        </table>
    </div>
</section>
<?php render_footer(); ?>
