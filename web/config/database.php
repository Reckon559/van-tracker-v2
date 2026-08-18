<?php
declare(strict_types=1);

function database(): PDO
{
    static $pdo = null;
    if ($pdo instanceof PDO) {
        return $pdo;
    }

    $host = getenv('VAN_TRACKER_DB_HOST') ?: '127.0.0.1';
    $port = getenv('VAN_TRACKER_DB_PORT') ?: '3306';
    $name = getenv('VAN_TRACKER_DB_NAME') ?: 'van_tracker_v2';
    $user = getenv('VAN_TRACKER_DB_USER') ?: 'root';
    $pass = getenv('VAN_TRACKER_DB_PASSWORD') ?: '';

    $dsn = "mysql:host={$host};port={$port};dbname={$name};charset=utf8mb4";
    $pdo = new PDO($dsn, $user, $pass, [
        PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
        PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
        PDO::ATTR_EMULATE_PREPARES => false,
    ]);

    return $pdo;
}

