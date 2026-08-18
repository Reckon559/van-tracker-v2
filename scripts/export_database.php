<?php
declare(strict_types=1);

/**
 * Exports the complete live MySQL database (schema + all data rows)
 * to `database/full_database_dump.sql` and `database/sample_data.sql`.
 * 
 * Usage:
 *   php scripts/export_database.php
 */

require_once dirname(__DIR__) . '/web/config/database.php';

try {
    $db = database();
    $dbName = getenv('VAN_TRACKER_DB_NAME') ?: 'van_tracker_v2';
    
    echo "=== Exporting Live Database [{$dbName}] ===\n";
    
    $outputFile = dirname(__DIR__) . '/database/full_database_dump.sql';
    $fp = fopen($outputFile, 'w');
    if (!$fp) {
        throw new RuntimeException("Could not open {$outputFile} for writing.");
    }
    
    fwrite($fp, "-- ========================================================\n");
    fwrite($fp, "-- Kathmandu School Van Tracking & Safety System (van-tracker-v2)\n");
    fwrite($fp, "-- Complete Database Export (Schema + Full Data)\n");
    fwrite($fp, "-- Generated at: " . date('Y-m-d H:i:s') . "\n");
    fwrite($fp, "-- ========================================================\n\n");
    
    fwrite($fp, "CREATE DATABASE IF NOT EXISTS `{$dbName}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;\n");
    fwrite($fp, "USE `{$dbName}`;\n\n");
    fwrite($fp, "SET FOREIGN_KEY_CHECKS = 0;\n");
    fwrite($fp, "SET SQL_MODE = 'NO_AUTO_VALUE_ON_ZERO';\n");
    fwrite($fp, "SET time_zone = '+00:00';\n\n");
    
    // Get all tables in dependency order
    $tables = $db->query("SHOW TABLES")->fetchAll(PDO::FETCH_COLUMN);
    
    // Table order to prevent foreign key issues on import
    $preferredOrder = [
        'users', 'vans', 'drivers', 'routes', 'students', 'route_students',
        'trips', 'trip_stops', 'trip_attendance', 'trip_telemetry',
        'anomaly_events', 'simulation_events', 'notifications', 'eta_predictions'
    ];
    
    // Sort tables according to preferred order
    usort($tables, function ($a, $b) use ($preferredOrder) {
        $posA = array_search($a, $preferredOrder, true);
        $posB = array_search($b, $preferredOrder, true);
        $posA = ($posA === false) ? 999 : $posA;
        $posB = ($posB === false) ? 999 : $posB;
        return $posA <=> $posB;
    });
    
    $totalExportedRows = 0;
    
    foreach ($tables as $table) {
        echo "Processing table `{$table}`... ";
        
        fwrite($fp, "-- --------------------------------------------------------\n");
        fwrite($fp, "-- Table structure for table `{$table}`\n");
        fwrite($fp, "-- --------------------------------------------------------\n");
        fwrite($fp, "DROP TABLE IF EXISTS `{$table}`;\n");
        
        $createTableStmt = $db->query("SHOW CREATE TABLE `{$table}`")->fetch(PDO::FETCH_ASSOC);
        fwrite($fp, $createTableStmt['Create Table'] . ";\n\n");
        
        // Export rows
        $stmt = $db->query("SELECT * FROM `{$table}`");
        $rows = $stmt->fetchAll(PDO::FETCH_ASSOC);
        $rowCount = count($rows);
        $totalExportedRows += $rowCount;
        
        if ($rowCount > 0) {
            fwrite($fp, "-- Dumping data for table `{$table}` ({$rowCount} rows)\n");
            
            // Insert in chunks of 500 rows for high performance
            $chunks = array_chunk($rows, 500);
            foreach ($chunks as $chunk) {
                $columns = array_keys($chunk[0]);
                $colNames = implode('`, `', $columns);
                fwrite($fp, "INSERT INTO `{$table}` (`{$colNames}`) VALUES\n");
                
                $valueStrings = [];
                foreach ($chunk as $row) {
                    $escapedValues = [];
                    foreach ($row as $val) {
                        if ($val === null) {
                            $escapedValues[] = 'NULL';
                        } elseif (is_numeric($val)) {
                            $escapedValues[] = $val;
                        } else {
                            $escapedValues[] = $db->quote((string)$val);
                        }
                    }
                    $valueStrings[] = "(" . implode(', ', $escapedValues) . ")";
                }
                fwrite($fp, implode(",\n", $valueStrings) . ";\n");
            }
            fwrite($fp, "\n");
        }
        echo "{$rowCount} rows exported.\n";
    }
    
    fwrite($fp, "SET FOREIGN_KEY_CHECKS = 1;\n");
    fclose($fp);
    
    // Also create a copy as database/schema_and_data.sql
    copy($outputFile, dirname(__DIR__) . '/database/schema_and_data.sql');
    
    echo "\n=== Export Complete! ===\n";
    echo "Total tables exported: " . count($tables) . "\n";
    echo "Total rows exported: {$totalExportedRows}\n";
    echo "File saved to: {$outputFile}\n";
    echo "File size: " . round(filesize($outputFile) / 1024, 2) . " KB\n";
    
} catch (Throwable $e) {
    echo "ERROR during export: " . $e->getMessage() . "\n";
    exit(1);
}
