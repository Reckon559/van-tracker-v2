<?php
declare(strict_types=1);

require_once dirname(__DIR__) . '/web/config/database.php';

try {
    $db = database();
    echo "=== MySQL Database: Connected successfully ===\n";
    $tables = $db->query("SHOW TABLES")->fetchAll(PDO::FETCH_COLUMN);
    echo "Total tables in database: " . count($tables) . "\n\n";

    foreach ($tables as $table) {
        $count = (int)$db->query("SELECT COUNT(*) FROM `{$table}`")->fetchColumn();
        echo "Table: `{$table}` - {$count} rows\n";
        if ($count > 0 && in_array($table, ['users', 'vans', 'routes', 'trips', 'students', 'stops'])) {
            $stmt = $db->query("SELECT * FROM `{$table}` LIMIT 5");
            $rows = $stmt->fetchAll(PDO::FETCH_ASSOC);
            foreach ($rows as $row) {
                // Don't show full password hash
                if (isset($row['password_hash'])) {
                    $row['password_hash'] = substr($row['password_hash'], 0, 12) . '...';
                }
                echo "   " . json_encode($row) . "\n";
            }
        }
    }
} catch (Throwable $e) {
    echo "ERROR: " . $e->getMessage() . "\n";
}
