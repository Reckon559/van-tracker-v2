<?php
declare(strict_types=1);

const APP_NAME = 'Kathmandu School Van Tracker';

$configuredBaseUrl = getenv('VAN_TRACKER_BASE_URL');
if ($configuredBaseUrl !== false && $configuredBaseUrl !== '') {
    define('APP_BASE_URL', rtrim($configuredBaseUrl, '/'));
} else {
    $script = $_SERVER['SCRIPT_NAME'] ?? '';
    $scriptDir = str_replace('\\', '/', dirname($script));
    if ($scriptDir === '/' || $scriptDir === '.') {
        $scriptDir = '';
    }
    
    // Trim known subfolders when the page is inside /admin, /driver, /parent, /api
    $subfolders = ['/admin', '/driver', '/parent', '/api'];
    foreach ($subfolders as $sub) {
        if (str_ends_with($scriptDir, $sub)) {
            $scriptDir = substr($scriptDir, 0, -strlen($sub));
            break;
        }
    }
    define('APP_BASE_URL', rtrim($scriptDir, '/'));
}

$configuredRoutingUrl = getenv('ROUTING_SERVICE_URL');
define(
    'ROUTING_SERVICE_URL',
    $configuredRoutingUrl !== false && $configuredRoutingUrl !== ''
        ? rtrim($configuredRoutingUrl, '/')
        : 'http://127.0.0.1:5000'
);

if (session_status() !== PHP_SESSION_ACTIVE) {
    session_set_cookie_params([
        'httponly' => true,
        'samesite' => 'Lax',
        'secure' => !empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off',
    ]);
    session_start();
}

