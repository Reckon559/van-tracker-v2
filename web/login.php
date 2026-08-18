<?php
declare(strict_types=1);

require_once __DIR__ . '/config/app.php';
require_once __DIR__ . '/config/database.php';
require_once __DIR__ . '/includes/auth.php';
require_once __DIR__ . '/includes/layout.php';

if (signed_in()) {
    redirect_to_dashboard();
}

$error = '';
$email = '';

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    verify_csrf();
    $email = strtolower(trim((string) ($_POST['email'] ?? '')));
    $password = (string) ($_POST['password'] ?? '');

    $statement = database()->prepare(
        'SELECT id, name, email, password_hash, role
         FROM users
         WHERE email = :email AND active = 1
         LIMIT 1'
    );
    $statement->execute(['email' => $email]);
    $user = $statement->fetch();

    if ($user && password_verify($password, $user['password_hash'])) {
        session_regenerate_id(true);
        $_SESSION['user_id'] = (int) $user['id'];
        $_SESSION['user_name'] = $user['name'];
        $_SESSION['user_role'] = $user['role'];
        redirect_to_dashboard();
    }

    $error = 'The email or password is incorrect.';
}

render_header('Sign in');
?>
<section class="auth-shell">
    <div class="auth-card">
        <div class="auth-icon">🚌</div>
        <h1>School Van Tracker</h1>
        <p>Sign in as an administrator, driver or parent.</p>

        <?php if ($error !== ''): ?>
            <div class="alert alert-danger"><?= escape($error) ?></div>
        <?php endif; ?>

        <form method="post" class="stack-form">
            <input type="hidden" name="csrf_token" value="<?= csrf_token() ?>">
            <label>
                Email
                <input type="email" name="email" value="<?= escape($email) ?>" required autofocus>
            </label>
            <label>
                Password
                <input type="password" name="password" required>
            </label>
            <button class="primary-button" type="submit">Sign in</button>
        </form>
    </div>
</section>
<?php render_footer(); ?>

