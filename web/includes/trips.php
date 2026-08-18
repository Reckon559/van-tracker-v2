<?php
declare(strict_types=1);

function read_json_request(): array
{
    $decoded = json_decode((string) file_get_contents('php://input'), true);
    if (!is_array($decoded)) {
        http_response_code(400);
        header('Content-Type: application/json');
        echo json_encode(['error' => 'A valid JSON request body is required.']);
        exit;
    }
    return $decoded;
}

function find_accessible_trip(PDO $pdo, int $tripId): ?array
{
    if (($_SESSION['user_role'] ?? null) === 'admin') {
        $statement = $pdo->prepare('SELECT * FROM trips WHERE id = :trip_id');
        $statement->execute(['trip_id' => $tripId]);
    } else {
        $statement = $pdo->prepare(
            'SELECT t.*
             FROM trips t
             JOIN drivers d ON d.id = t.driver_id
             WHERE t.id = :trip_id AND d.user_id = :user_id'
        );
        $statement->execute([
            'trip_id' => $tripId,
            'user_id' => $_SESSION['user_id'],
        ]);
    }
    return $statement->fetch() ?: null;
}

function json_result(array $payload, int $status = 200): never
{
    http_response_code($status);
    header('Content-Type: application/json');
    echo json_encode($payload, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    exit;
}

function scenario_eta_multiplier(
    string $traffic,
    string $weather,
    string $schoolPeriod,
    int $hour,
    int $dayOfWeek,
    bool $incident = false
): float {
    $trafficFactor = ['low' => 1.00, 'medium' => 1.35, 'high' => 1.90][$traffic] ?? 1.35;
    $weatherFactor = [
        'clear' => 1.00, 'rain' => 1.14,
        'heavy_rain' => 1.34, 'fog' => 1.22,
    ][$weather] ?? 1.00;
    $hourFactor = in_array($hour, [7, 8, 9, 14, 15, 16, 17], true)
        ? 1.18
        : (in_array($hour, [10, 11, 12, 13, 18], true) ? 1.08 : 0.94);
    $schoolFactor = [
        'regular' => 1.00, 'exam' => 1.04, 'half_day' => 1.10,
    ][$schoolPeriod] ?? 1.00;
    $dayFactor = in_array($dayOfWeek, [5, 6], true) ? 0.92 : 1.00;
    return $trafficFactor * $weatherFactor * $hourFactor
        * $schoolFactor * $dayFactor * ($incident ? 1.35 : 1.00);
}
