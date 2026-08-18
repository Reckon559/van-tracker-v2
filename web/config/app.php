<?php
declare(strict_types=1);

const APP_NAME = 'Kathmandu School Van Tracker';

$configuredBaseUrl = getenv('VAN_TRACKER_BASE_URL');
define(
    'APP_BASE_URL',
    $configuredBaseUrl !== false && $configuredBaseUrl !== ''
        ? rtrim($configuredBaseUrl, '/')
        : '/van-tracker-v2/web'
);

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

