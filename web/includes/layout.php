<?php
declare(strict_types=1);

function render_header(string $title): void
{
    $userName = isset($_SESSION['user_name']) ? escape((string) $_SESSION['user_name']) : '';
    $role = isset($_SESSION['user_role']) ? escape(ucfirst((string) $_SESSION['user_role'])) : '';
    ?>
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title><?= escape($title) ?> · <?= escape(APP_NAME) ?></title>
    <link rel="stylesheet" href="<?= APP_BASE_URL ?>/assets/css/app.css?v=16">
</head>
<body>
<header class="topbar">
    <a class="brand" href="<?= APP_BASE_URL ?>/index.php">🚌 <?= escape(APP_NAME) ?></a>
    <?php if (signed_in()): ?>
        <div class="user-area">
            <span><?= $userName ?> · <?= $role ?></span>
            <form action="<?= APP_BASE_URL ?>/logout.php" method="post">
                <input type="hidden" name="csrf_token" value="<?= csrf_token() ?>">
                <button class="link-button" type="submit">Log out</button>
            </form>
        </div>
    <?php endif; ?>
</header>
<main class="page">
    <?php if ($flash = take_flash()): ?>
        <div class="alert <?= $flash['type'] === 'danger' ? 'alert-danger' : 'alert-success' ?>">
            <?= escape((string) $flash['message']) ?>
        </div>
    <?php endif; ?>
    <?php
}

function render_footer(): void
{
    ?>
</main>
</body>
</html>
    <?php
}

function status_card(string $label, string|int $value, string $hint = ''): void
{
    ?>
    <article class="metric-card">
        <span class="metric-label"><?= escape($label) ?></span>
        <strong><?= escape((string) $value) ?></strong>
        <?php if ($hint !== ''): ?>
            <small><?= escape($hint) ?></small>
        <?php endif; ?>
    </article>
    <?php
}

function render_admin_navigation(string $active): void
{
    $items = [
        'dashboard' => ['Dashboard', '/admin/dashboard.php'],
        'vans' => ['Vans', '/admin/manage-vans.php'],
        'drivers' => ['Drivers', '/admin/manage-drivers.php'],
        'students' => ['Students', '/admin/manage-students.php'],
        'routes' => ['Routes', '/admin/manage-routes.php'],
        'trips' => ['Trips', '/admin/manage-trips.php'],
        'route-demo' => ['ETA Lab', '/route-demo.php'],
    ];
    ?>
    <nav class="section-nav" aria-label="Administrator navigation">
        <?php foreach ($items as $key => [$label, $path]): ?>
            <a class="<?= $key === $active ? 'active' : '' ?>"
               href="<?= APP_BASE_URL . $path ?>"><?= escape($label) ?></a>
        <?php endforeach; ?>
    </nav>
    <?php
}

function render_driver_navigation(string $active): void
{
    $items = [
        'dashboard' => ['Dashboard', '/driver/dashboard.php'],
        'control' => ['Trip control', '/trip-control.php'],
        'history' => ['Trip history', '/driver/trip-history.php'],
    ];
    ?>
    <nav class="section-nav driver-navigation" aria-label="Driver navigation">
        <?php foreach ($items as $key => [$label, $path]): ?>
            <a class="<?= $key === $active ? 'active' : '' ?>"
               href="<?= APP_BASE_URL . $path ?>"><?= escape($label) ?></a>
        <?php endforeach; ?>
    </nav>
    <?php
}

function render_form_errors(array $errors): void
{
    if (!$errors) {
        return;
    }
    ?>
    <div class="alert alert-danger">
        <strong>Please correct the following:</strong>
        <ul class="error-list">
            <?php foreach ($errors as $error): ?>
                <li><?= escape((string) $error) ?></li>
            <?php endforeach; ?>
        </ul>
    </div>
    <?php
}
