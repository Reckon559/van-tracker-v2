<?php
declare(strict_types=1);

/**
 * Ensures clean, known login passwords for all 5 demo accounts
 * so that any friend or examiner can log in immediately.
 * 
 * Passwords set:
 *   admin@example.com    -> admin123
 *   prashant@example.com -> driver123
 *   mandi@example.com    -> parent123
 *   jun@example.com      -> parent123
 *   shyam@example.com    -> parent123
 */

require_once dirname(__DIR__) . '/web/config/database.php';

try {
    $db = database();
    
    $accounts = [
        ['email' => 'admin@example.com', 'pass' => 'admin123', 'name' => 'Niraj Ghimire', 'role' => 'admin'],
        ['email' => 'prashant@example.com', 'pass' => 'driver123', 'name' => 'Prashant', 'role' => 'driver'],
        ['email' => 'mandi@example.com', 'pass' => 'parent123', 'name' => 'Mandi', 'role' => 'parent'],
        ['email' => 'jun@example.com', 'pass' => 'parent123', 'name' => 'Jun', 'role' => 'parent'],
        ['email' => 'shyam@example.com', 'pass' => 'parent123', 'name' => 'Shyam', 'role' => 'parent'],
    ];
    
    foreach ($accounts as $acc) {
        $hash = password_hash($acc['pass'], PASSWORD_DEFAULT);
        
        // Update if exists, insert if not
        $check = $db->prepare("SELECT id FROM users WHERE email = :email");
        $check->execute(['email' => $acc['email']]);
        $exists = $check->fetchColumn();
        
        if ($exists) {
            $stmt = $db->prepare("UPDATE users SET password_hash = :hash, role = :role, active = 1 WHERE email = :email");
            $stmt->execute(['hash' => $hash, 'role' => $acc['role'], 'email' => $acc['email']]);
        } else {
            $stmt = $db->prepare("INSERT INTO users (name, email, password_hash, role, active) VALUES (:name, :email, :hash, :role, 1)");
            $stmt->execute(['name' => $acc['name'], 'email' => $acc['email'], 'hash' => $hash, 'role' => $acc['role']]);
        }
    }
    
    echo "Demo login passwords successfully configured.\n";
} catch (Throwable $e) {
    echo "Seed Error: " . $e->getMessage() . "\n";
}
