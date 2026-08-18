<?php
declare(strict_types=1);

require_once __DIR__ . '/config/app.php';
require_once __DIR__ . '/includes/auth.php';

if (signed_in()) {
    redirect_to_dashboard();
}

header('Location: ' . APP_BASE_URL . '/login.php');
exit;

