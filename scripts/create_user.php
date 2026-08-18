<?php
declare(strict_types=1);

require_once dirname(__DIR__) . '/web/config/database.php';

if (PHP_SAPI !== 'cli') {
    http_response_code(404);
    exit;
}

if ($argc !== 5) {
    fwrite(STDERR, "Usage: php scripts/create_user.php \"Name\" email@example.com \"Password\" admin|driver|parent\n");
    exit(1);
}

[$script, $name, $email, $password, $role] = $argv;
$email = strtolower(trim($email));
$allowedRoles = ['admin', 'driver', 'parent'];

if (!filter_var($email, FILTER_VALIDATE_EMAIL)) {
    fwrite(STDERR, "The email address is invalid.\n");
    exit(1);
}

if (strlen($password) < 8) {
    fwrite(STDERR, "Use a password containing at least eight characters.\n");
    exit(1);
}

if (!in_array($role, $allowedRoles, true)) {
    fwrite(STDERR, "Role must be admin, driver or parent.\n");
    exit(1);
}

$statement = database()->prepare(
    'INSERT INTO users (name, email, password_hash, role)
     VALUES (:name, :email, :password_hash, :role)'
);

try {
    $statement->execute([
        'name' => trim($name),
        'email' => $email,
        'password_hash' => password_hash($password, PASSWORD_DEFAULT),
        'role' => $role,
    ]);
} catch (PDOException $exception) {
    if ((int) $exception->errorInfo[1] === 1062) {
        fwrite(STDERR, "A user with that email already exists.\n");
        exit(1);
    }
    throw $exception;
}

fwrite(STDOUT, "Created {$role} user {$email}.\n");

