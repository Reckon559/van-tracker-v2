# =========================================================================
#  Kathmandu School Van Tracking & Safety System (van-tracker-v2)
#  PowerShell 1-Click System Launcher
# =========================================================================

Write-Host "=========================================================================" -ForegroundColor Green
Write-Host "   Kathmandu School Van Tracking & Safety System (van-tracker-v2)        " -ForegroundColor Green
Write-Host "                 1-Click Full System Startup (PowerShell)                " -ForegroundColor Green
Write-Host "=========================================================================" -ForegroundColor Green
Write-Host ""

$RootPath = $PSScriptRoot

# 1. Locate PHP
Write-Host "[1/4] Checking PHP runtime..." -ForegroundColor Cyan
$PhpPath = (Get-Command php.exe -ErrorAction SilentlyContinue).Source
if (-not $PhpPath -and (Test-Path "C:\xampp\php\php.exe")) {
    $PhpPath = "C:\xampp\php\php.exe"
}
if (-not $PhpPath) {
    Write-Host "[ERROR] PHP not found. Please install XAMPP or add PHP to PATH." -ForegroundColor Red
    pause
    exit 1
}
Write-Host "   -- PHP found: $PhpPath"

# 2. Locate Python
Write-Host "[2/4] Checking Python Routing & ML Environment..." -ForegroundColor Cyan
$PythonPath = "$RootPath\routing-service\.venv\Scripts\python.exe"
if (-not (Test-Path $PythonPath)) {
    $PythonPath = (Get-Command python.exe -ErrorAction SilentlyContinue).Source
    if ($PythonPath) {
        Write-Host "   -- Creating Python venv in routing-service\.venv..."
        & python -m venv "$RootPath\routing-service\.venv"
        $PythonPath = "$RootPath\routing-service\.venv\Scripts\python.exe"
        & $PythonPath -m pip install --upgrade pip
        & $PythonPath -m pip install -r "$RootPath\routing-service\requirements.txt" matplotlib seaborn
    }
}
if (-not (Test-Path $PythonPath)) {
    Write-Host "[ERROR] Python not found. Please install Python 3.10+." -ForegroundColor Red
    pause
    exit 1
}
Write-Host "   -- Python found: $PythonPath"

# 3. Initialize Database
Write-Host "[3/4] Initializing MySQL Database & Checking Service..." -ForegroundColor Cyan
$MySqlPort = Get-NetTCPConnection -LocalPort 3306 -ErrorAction SilentlyContinue
if (-not $MySqlPort) {
    if (Test-Path "C:\xampp\mysql_start.bat") {
        Write-Host "   -- MySQL not detected on port 3306. Starting XAMPP MySQL automatically..."
        Start-Process "C:\xampp\mysql_start.bat" -WindowStyle Minimized
        Start-Sleep -Seconds 4
    }
}
& $PhpPath "$RootPath\scripts\import_database.php"

# 4. Start Python Service
Write-Host "[4/4] Starting Background Services..." -ForegroundColor Cyan
Write-Host "   -- Launching Python Routing & ML Engine (Port 5000)..."
Start-Process -FilePath "cmd.exe" -ArgumentList "/k", "cd /d `"$RootPath\routing-service`" && `"$PythonPath`" app.py" -WindowStyle Normal

Start-Sleep -Seconds 2

# 5. Start Web Server
Write-Host "   -- Launching PHP Web Server (Port 8000)..."
Start-Process -FilePath "cmd.exe" -ArgumentList "/k", "cd /d `"$RootPath`" && `"$PhpPath`" -S 0.0.0.0:8000 -t web" -WindowStyle Normal

Start-Sleep -Seconds 1

# 6. Open Browser
Start-Process "http://127.0.0.1:8000/login.php"

Write-Host ""
Write-Host "=========================================================================" -ForegroundColor Green
Write-Host "                 ALL SERVICES ARE NOW RUNNING!                           " -ForegroundColor Green
Write-Host "=========================================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Web Application:    http://127.0.0.1:8000/login.php"
Write-Host "  Routing ML Service: http://127.0.0.1:5000/health"
Write-Host ""
Write-Host "  Login Credentials:" -ForegroundColor Yellow
Write-Host "    [Admin]  admin@example.com    / admin123"
Write-Host "    [Driver] prashant@example.com / driver123"
Write-Host "    [Parent] mandi@example.com    / parent123"
Write-Host ""
pause
