<?php
declare(strict_types=1);

function escape(string $value): string
{
    return htmlspecialchars($value, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
}

function csrf_token(): string
{
    if (empty($_SESSION['csrf_token'])) {
        $_SESSION['csrf_token'] = bin2hex(random_bytes(32));
    }
    return $_SESSION['csrf_token'];
}

function verify_csrf(): void
{
    $submitted = $_POST['csrf_token'] ?? '';
    if (!is_string($submitted) || !hash_equals(csrf_token(), $submitted)) {
        http_response_code(419);
        exit('The form expired. Go back, refresh the page and try again.');
    }
}

function verify_csrf_header(): void
{
    $submitted = $_SERVER['HTTP_X_CSRF_TOKEN'] ?? '';
    if (!is_string($submitted) || !hash_equals(csrf_token(), $submitted)) {
        http_response_code(419);
        header('Content-Type: application/json');
        echo json_encode(['error' => 'The request expired. Refresh and try again.']);
        exit;
    }
}

function set_flash(string $type, string $message): void
{
    $_SESSION['flash_message'] = [
        'type' => $type,
        'message' => $message,
    ];
}

function take_flash(): ?array
{
    $flash = $_SESSION['flash_message'] ?? null;
    unset($_SESSION['flash_message']);
    return is_array($flash) ? $flash : null;
}

function redirect(string $path): never
{
    header('Location: ' . APP_BASE_URL . $path);
    exit;
}

function positive_int(mixed $value): ?int
{
    $filtered = filter_var($value, FILTER_VALIDATE_INT, [
        'options' => ['min_range' => 1],
    ]);
    return $filtered === false ? null : (int) $filtered;
}

function valid_coordinate(mixed $value, float $minimum, float $maximum): ?float
{
    if (!is_numeric($value)) {
        return null;
    }
    $number = (float) $value;
    return $number >= $minimum && $number <= $maximum ? $number : null;
}

function signed_in(): bool
{
    return isset($_SESSION['user_id'], $_SESSION['user_role']);
}

function require_role(string $role): void
{
    if (!signed_in()) {
        header('Location: ' . APP_BASE_URL . '/login.php');
        exit;
    }

    if ($_SESSION['user_role'] !== $role) {
        redirect_to_dashboard();
    }
}

function require_any_role(array $roles): void
{
    if (!signed_in()) {
        header('Location: ' . APP_BASE_URL . '/login.php');
        exit;
    }

    if (!in_array($_SESSION['user_role'], $roles, true)) {
        redirect_to_dashboard();
    }
}

function redirect_to_dashboard(): never
{
    $role = $_SESSION['user_role'] ?? null;
    $target = match ($role) {
        'admin' => '/admin/dashboard.php',
        'driver' => '/driver/dashboard.php',
        'parent' => '/parent/dashboard.php',
        default => '/login.php',
    };

    redirect($target);
}
