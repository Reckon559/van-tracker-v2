<?php
declare(strict_types=1);

/**
 * 1-Click Database Importer for van-tracker-v2
 * 
 * Streams and executes SQL statements individually to avoid max_allowed_packet limitations.
 * 
 * Usage:
 *   php scripts/import_database.php
 */

$host = getenv('VAN_TRACKER_DB_HOST') ?: '127.0.0.1';
$port = getenv('VAN_TRACKER_DB_PORT') ?: '3306';
$name = getenv('VAN_TRACKER_DB_NAME') ?: 'van_tracker_v2';
$user = getenv('VAN_TRACKER_DB_USER') ?: 'root';
$pass = getenv('VAN_TRACKER_DB_PASSWORD') ?: '';

$dumpFile = dirname(__DIR__) . '/database/full_database_dump.sql';
if (!file_exists($dumpFile)) {
    $dumpFile = dirname(__DIR__) . '/database/schema_and_data.sql';
}

if (!file_exists($dumpFile)) {
    echo "ERROR: SQL dump file not found in database/ directory.\n";
    exit(1);
}

try {
    echo "=== 1-Click Database Setup: van-tracker-v2 ===\n";
    echo "Connecting to MySQL server at {$host}:{$port}...\n";
    
    // Connect without dbname first to ensure database exists
    $dsnNoDb = "mysql:host={$host};port={$port};charset=utf8mb4";
    $pdo = new PDO($dsnNoDb, $user, $pass, [
        PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
    ]);
    
    echo "Creating database `{$name}` if not exists...\n";
    $pdo->exec("CREATE DATABASE IF NOT EXISTS `{$name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci");
    $pdo->exec("USE `{$name}`");
    
    echo "Importing database from " . basename($dumpFile) . " (" . round(filesize($dumpFile) / 1024, 2) . " KB)...\n";
    
    $pdo->exec("SET FOREIGN_KEY_CHECKS = 0");
    $pdo->exec("SET SQL_MODE = 'NO_AUTO_VALUE_ON_ZERO'");
    
    $fp = fopen($dumpFile, 'r');
    if (!$fp) {
        throw new RuntimeException("Could not open {$dumpFile}");
    }
    
    $currentQuery = '';
    $statementCount = 0;
    
    while (($line = fgets($fp)) !== false) {
        $trimmed = trim($line);
        // Skip comment lines and empty lines
        if ($trimmed === '' || str_starts_with($trimmed, '--') || str_starts_with($trimmed, '/*')) {
            continue;
        }
        
        $currentQuery .= $line;
        
        // If line ends with semicolon, execute statement
        if (str_ends_with($trimmed, ';')) {
            $pdo->exec($currentQuery);
            $currentQuery = '';
            $statementCount++;
            if ($statementCount % 20 === 0) {
                echo ".";
            }
        }
    }
    fclose($fp);
    
    $pdo->exec("SET FOREIGN_KEY_CHECKS = 1");
    echo "\nExecuted {$statementCount} SQL statements.\n";
    
    // Verify import
    $tables = $pdo->query("SHOW TABLES")->fetchAll(PDO::FETCH_COLUMN);
    $userCount = (int)$pdo->query("SELECT COUNT(*) FROM users")->fetchColumn();
    $vanCount = (int)$pdo->query("SELECT COUNT(*) FROM vans")->fetchColumn();
    $routeCount = (int)$pdo->query("SELECT COUNT(*) FROM routes")->fetchColumn();
    $tripCount = (int)$pdo->query("SELECT COUNT(*) FROM trips")->fetchColumn();
    $telemetryCount = (int)$pdo->query("SELECT COUNT(*) FROM trip_telemetry")->fetchColumn();
    
    echo "\n=== Database Successfully Initialized & Imported! ===\n";
    echo "Total Tables: " . count($tables) . "\n";
    echo "Users imported: {$userCount}\n";
    echo "Vans imported: {$vanCount}\n";
    echo "Routes imported: {$routeCount}\n";
    echo "Trips imported: {$tripCount}\n";
    echo "Telemetry records: {$telemetryCount}\n\n";
    
    echo "User Accounts Available:\n";
    $users = $pdo->query("SELECT name, email, role FROM users")->fetchAll(PDO::FETCH_ASSOC);
    foreach ($users as $u) {
        echo "  - [{$u['role']}] {$u['name']} ({$u['email']})\n";
    }
    
} catch (Throwable $e) {
    echo "\nIMPORT ERROR: " . $e->getMessage() . "\n";
    echo "Make sure MySQL is running in XAMPP on port {$port}.\n";
    exit(1);
}
