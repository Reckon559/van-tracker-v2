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
    'student_id' => '',
    'student_name' => '',
    'parent_id' => '',
    'new_parent_name' => '',
    'new_parent_email' => '',
    'van_id' => '',
    'pickup_location' => '',
    'pickup_lat' => '',
    'pickup_lng' => '',
];

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    verify_csrf();
    $action = (string) ($_POST['action'] ?? '');

    if ($action === 'toggle') {
        $studentId = positive_int($_POST['student_id'] ?? null);
        if ($studentId !== null) {
            $statement = $pdo->prepare(
                'UPDATE students SET active = IF(active = 1, 0, 1) WHERE id = :id'
            );
            $statement->execute(['id' => $studentId]);
            set_flash('success', 'Student status updated.');
        }
        redirect('/admin/manage-students.php');
    }

    if ($action === 'save') {
        $form = [
            'student_id' => trim((string) ($_POST['student_id'] ?? '')),
            'student_name' => trim((string) ($_POST['student_name'] ?? '')),
            'parent_id' => trim((string) ($_POST['parent_id'] ?? '')),
            'new_parent_name' => trim((string) ($_POST['new_parent_name'] ?? '')),
            'new_parent_email' => strtolower(trim((string) ($_POST['new_parent_email'] ?? ''))),
            'van_id' => trim((string) ($_POST['van_id'] ?? '')),
            'pickup_location' => trim((string) ($_POST['pickup_location'] ?? '')),
            'pickup_lat' => trim((string) ($_POST['pickup_lat'] ?? '')),
            'pickup_lng' => trim((string) ($_POST['pickup_lng'] ?? '')),
        ];
        $password = (string) ($_POST['new_parent_password'] ?? '');
        $studentId = $form['student_id'] === '' ? null : positive_int($form['student_id']);
        $parentId = $form['parent_id'] === '' ? null : positive_int($form['parent_id']);
        $vanId = positive_int($form['van_id']);
        $latitude = valid_coordinate($form['pickup_lat'], -90, 90);
        $longitude = valid_coordinate($form['pickup_lng'], -180, 180);

        if ($form['student_name'] === '') $errors[] = 'Student name is required.';
        if ($vanId === null) $errors[] = 'Select a van.';
        if ($form['pickup_location'] === '') $errors[] = 'Pickup location name is required.';
        if ($latitude === null || $longitude === null) {
            $errors[] = 'Select a valid pickup point on the map.';
        }
        if ($parentId === null) {
            if ($form['new_parent_name'] === '') $errors[] = 'New parent name is required.';
            if (!filter_var($form['new_parent_email'], FILTER_VALIDATE_EMAIL)) {
                $errors[] = 'Enter a valid new parent email.';
            }
            if (strlen($password) < 8) {
                $errors[] = 'New parent password must contain at least eight characters.';
            }
        }

        if (!$errors) {
            try {
                $pdo->beginTransaction();
                if ($parentId === null) {
                    $parentStatement = $pdo->prepare(
                        'INSERT INTO users (name, email, password_hash, role)
                         VALUES (:name, :email, :password_hash, :role)'
                    );
                    $parentStatement->execute([
                        'name' => $form['new_parent_name'],
                        'email' => $form['new_parent_email'],
                        'password_hash' => password_hash($password, PASSWORD_DEFAULT),
                        'role' => 'parent',
                    ]);
                    $parentId = (int) $pdo->lastInsertId();
                }

                if ($studentId === null) {
                    $statement = $pdo->prepare(
                        'INSERT INTO students
                            (name, parent_id, van_id, pickup_location,
                             pickup_lat, pickup_lng)
                         VALUES
                            (:name, :parent_id, :van_id, :pickup_location,
                             :pickup_lat, :pickup_lng)'
                    );
                } else {
                    $statement = $pdo->prepare(
                        'UPDATE students
                         SET name = :name, parent_id = :parent_id, van_id = :van_id,
                             pickup_location = :pickup_location,
                             pickup_lat = :pickup_lat, pickup_lng = :pickup_lng
                         WHERE id = :id'
                    );
                }
                $parameters = [
                    'name' => $form['student_name'],
                    'parent_id' => $parentId,
                    'van_id' => $vanId,
                    'pickup_location' => $form['pickup_location'],
                    'pickup_lat' => $latitude,
                    'pickup_lng' => $longitude,
                ];
                if ($studentId !== null) $parameters['id'] = $studentId;
                $statement->execute($parameters);
                $pdo->commit();

                set_flash('success', $studentId === null ? 'Student and parent assignment created.' : 'Student updated.');
                redirect('/admin/manage-students.php');
            } catch (Throwable $exception) {
                if ($pdo->inTransaction()) $pdo->rollBack();
                if ($exception instanceof PDOException
                    && (int) ($exception->errorInfo[1] ?? 0) === 1062) {
                    $errors[] = 'The new parent email already exists. Select that parent from the list.';
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
        'SELECT id AS student_id, name AS student_name, parent_id, van_id,
                pickup_location, pickup_lat, pickup_lng
         FROM students WHERE id = :id'
    );
    $statement->execute(['id' => $editId]);
    if ($record = $statement->fetch()) {
        foreach ($record as $key => $value) {
            $form[$key] = $value === null ? '' : (string) $value;
        }
    }
}

$parents = $pdo->query(
    "SELECT id, name, email FROM users
     WHERE role = 'parent' AND active = 1 ORDER BY name"
)->fetchAll();
$vans = $pdo->query(
    'SELECT id, van_number FROM vans WHERE active = 1 ORDER BY van_number'
)->fetchAll();
$students = $pdo->query(
    'SELECT s.id, s.name AS student_name, s.pickup_location,
            s.pickup_lat, s.pickup_lng, s.active,
            p.name AS parent_name, p.email AS parent_email,
            v.van_number
     FROM students s
     JOIN users p ON p.id = s.parent_id
     JOIN vans v ON v.id = s.van_id
     ORDER BY s.active DESC, s.name'
)->fetchAll();

render_header('Manage students');
render_admin_navigation('students');
?>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<div class="page-heading">
    <div>
        <span class="eyebrow">Administrator</span>
        <h1>Manage students</h1>
        <p>Assign each student, parent, van and exact home pickup coordinate.</p>
    </div>
</div>

<section class="panel">
    <h2><?= $form['student_id'] === '' ? 'Add student' : 'Edit student' ?></h2>
    <?php render_form_errors($errors); ?>
    <form method="post" class="form-grid" id="student-form">
        <input type="hidden" name="csrf_token" value="<?= csrf_token() ?>">
        <input type="hidden" name="action" value="save">
        <input type="hidden" name="student_id" value="<?= escape($form['student_id']) ?>">

        <label>Student name
            <input name="student_name" value="<?= escape($form['student_name']) ?>" required>
        </label>
        <label>Assign van
            <select name="van_id" required>
                <option value="">Select van</option>
                <?php foreach ($vans as $van): ?>
                    <option value="<?= (int) $van['id'] ?>"
                        <?= (string) $van['id'] === $form['van_id'] ? 'selected' : '' ?>>
                        <?= escape($van['van_number']) ?>
                    </option>
                <?php endforeach; ?>
            </select>
        </label>

        <label class="full-width">Use an existing parent
            <select name="parent_id" id="parent-id">
                <option value="">Create a new parent account</option>
                <?php foreach ($parents as $parent): ?>
                    <option value="<?= (int) $parent['id'] ?>"
                        <?= (string) $parent['id'] === $form['parent_id'] ? 'selected' : '' ?>>
                        <?= escape($parent['name']) ?> — <?= escape($parent['email']) ?>
                    </option>
                <?php endforeach; ?>
            </select>
        </label>

        <div class="full-width form-grid" id="new-parent-fields">
            <label>New parent name
                <input name="new_parent_name" value="<?= escape($form['new_parent_name']) ?>">
            </label>
            <label>New parent email
                <input type="email" name="new_parent_email"
                       value="<?= escape($form['new_parent_email']) ?>">
            </label>
            <label>New parent password
                <input type="password" name="new_parent_password" minlength="8">
            </label>
        </div>

        <div class="full-width location-picker"
             data-location-picker
             data-name-input="pickup-location"
             data-lat-input="pickup-lat"
             data-lng-input="pickup-lng">
            <h3>Home pickup point</h3>
            <div class="location-search-row">
                <input data-role="search" placeholder="Search Balkhu, Kalanki, Baneshwor…"
                       value="<?= escape($form['pickup_location']) ?>">
                <button type="button" data-role="search-button">Search</button>
            </div>
            <div class="location-results" data-role="results"></div>
            <label>Pickup location name
                <input id="pickup-location" name="pickup_location"
                       value="<?= escape($form['pickup_location']) ?>" required>
            </label>
            <div class="coordinate-grid">
                <label>Latitude
                    <input id="pickup-lat" name="pickup_lat" type="number" step="any"
                           value="<?= escape($form['pickup_lat']) ?>" required>
                </label>
                <label>Longitude
                    <input id="pickup-lng" name="pickup_lng" type="number" step="any"
                           value="<?= escape($form['pickup_lng']) ?>" required>
                </label>
            </div>
            <div class="location-map" data-role="map"></div>
        </div>

        <div class="inline-actions full-width">
            <button type="submit"><?= $form['student_id'] === '' ? 'Add student' : 'Save changes' ?></button>
            <?php if ($form['student_id'] !== ''): ?>
                <a class="primary-button secondary-button" href="<?= APP_BASE_URL ?>/admin/manage-students.php">Cancel</a>
            <?php endif; ?>
        </div>
    </form>
</section>

<section class="panel">
    <h2>All students</h2>
    <div class="data-table-wrap">
        <table class="data-table">
            <thead><tr>
                <th>Student</th><th>Parent</th><th>Van</th><th>Pickup</th>
                <th>Status</th><th>Actions</th>
            </tr></thead>
            <tbody>
            <?php foreach ($students as $student): ?>
                <tr>
                    <td><?= escape($student['student_name']) ?></td>
                    <td><?= escape($student['parent_name']) ?><br><small><?= escape($student['parent_email']) ?></small></td>
                    <td><?= escape($student['van_number']) ?></td>
                    <td><?= escape($student['pickup_location']) ?><br>
                        <small><?= escape((string) $student['pickup_lat']) ?>, <?= escape((string) $student['pickup_lng']) ?></small>
                    </td>
                    <td><span class="status-badge <?= $student['active'] ? '' : 'inactive' ?>">
                        <?= $student['active'] ? 'Active' : 'Inactive' ?>
                    </span></td>
                    <td><div class="inline-actions">
                        <a class="primary-button small-button secondary-button"
                           href="?edit=<?= (int) $student['id'] ?>">Edit</a>
                        <form method="post">
                            <input type="hidden" name="csrf_token" value="<?= csrf_token() ?>">
                            <input type="hidden" name="action" value="toggle">
                            <input type="hidden" name="student_id" value="<?= (int) $student['id'] ?>">
                            <button class="small-button <?= $student['active'] ? 'danger-button' : '' ?>">
                                <?= $student['active'] ? 'Deactivate' : 'Activate' ?>
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
<script>
(function () {
    const parentSelect = document.getElementById('parent-id');
    const newFields = document.getElementById('new-parent-fields');
    function updateParentFields() {
        newFields.hidden = parentSelect.value !== '';
    }
    parentSelect.addEventListener('change', updateParentFields);
    updateParentFields();
})();
</script>
<?php render_footer(); ?>

