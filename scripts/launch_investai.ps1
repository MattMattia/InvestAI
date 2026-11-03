# scripts/launch_investai.ps1
# InvestAI Enterprise - Orquestador de Inicio Rapido y Lanzador de Aplicacion de Escritorio

$ErrorActionPreference = 'Stop'

# 1. Fijar directorio en la raiz del proyecto
$rootDir = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location -LiteralPath $rootDir
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "   INVESTAI ENTERPRISE - DESKTOP LAUNCHER & ORCHESTRATOR" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "[InvestAI] Directorio de trabajo: $rootDir" -ForegroundColor Gray

# 2. Detener instancias previas preventivamente
$stopScript = Join-Path $PSScriptRoot "stop_investai.ps1"
if (Test-Path $stopScript) {
    & $stopScript
}

# 3. Detectar ejecutable de Python
$venvPython = Join-Path $rootDir ".venv\Scripts\python.exe"
$localAppPython = "$env:LOCALAPPDATA\Python\bin\python.exe"
if (Test-Path $venvPython) {
    $pythonCmd = $venvPython
} elseif (Test-Path $localAppPython) {
    $pythonCmd = $localAppPython
} else {
    $cmdPython = (Get-Command "python.exe" -ErrorAction SilentlyContinue)
    if ($cmdPython) {
        $pythonCmd = $cmdPython.Source
    } else {
        $pythonCmd = "python"
    }
}

# 4. Configurar PYTHONPATH para backend
$backendDir = Join-Path $rootDir "backend"
$env:PYTHONPATH = $backendDir

# 5. Ejecutar la semilla de demostracion rapida
Write-Host "[InvestAI] Verificando semilla institucional..." -ForegroundColor Cyan
$seedScript = Join-Path $rootDir "backend\scripts\seed_smoke_test.py"
& $pythonCmd $seedScript

# 6. Lanzar Backend FastAPI y Frontend Vite en paralelo
Write-Host "[InvestAI] Iniciando servicios Backend (8000) y Frontend (5173)..." -ForegroundColor Cyan
$backendProc = Start-Process -FilePath $pythonCmd -ArgumentList "-m uvicorn app.main:app --host 127.0.0.1 --port 8000" -WindowStyle Hidden -PassThru
$frontendProc = Start-Process -FilePath "cmd.exe" -ArgumentList "/c npm --prefix frontend run dev -- --port 5173 --strictPort" -WindowStyle Hidden -PassThru

# 7. Bucle reactivo ultrarrapido (250ms) para Healthcheck
Write-Host "[InvestAI] Sincronizando motores (Healthcheck)..." -ForegroundColor Yellow
$maxAttempts = 80 # 80 * 250ms = 20 segundos max
$attempt = 0
$healthy = $false

while ($attempt -lt $maxAttempts) {
    Start-Sleep -Milliseconds 250
    $attempt++
    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:8000/health" -UseBasicParsing -TimeoutSec 1 -ErrorAction Stop
        if ($response.StatusCode -eq 200) {
            $healthy = $true
            Write-Host "[InvestAI] Backend saludable en $([math]::Round($attempt * 0.25, 2))s (PID: $($backendProc.Id))." -ForegroundColor Green
            break
        }
    } catch {
        # Reintentar
    }
}

if (-not $healthy) {
    Write-Warning "[InvestAI] Tiempo de espera de healthcheck agotado. Continuando lanzamiento..."
}

# 8. Lanzamiento en Modo Aplicacion de Escritorio
$candidateBrowsers = @(
    "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "C:\Program Files\Google\Chrome\Application\chrome.exe"
)

$selectedBrowser = $null
foreach ($browser in $candidateBrowsers) {
    if (Test-Path $browser) {
        $selectedBrowser = $browser
        break
    }
}

Write-Host "[InvestAI] Abriendo aplicacion de escritorio..." -ForegroundColor Cyan
if ($selectedBrowser) {
    Start-Process -FilePath $selectedBrowser -ArgumentList "--app=http://localhost:5173", "--window-size=1440,900" -PassThru | Out-Null
} else {
    Start-Process "http://localhost:5173"
}

Write-Host "==========================================================" -ForegroundColor Green
Write-Host "   INVESTAI ENTERPRISE ACTIVO (PIDs: $($backendProc.Id), $($frontendProc.Id))" -ForegroundColor Green
Write-Host "   Credenciales demo: demo@investai.com / InvestAI2026!" -ForegroundColor Green
Write-Host "   Para detener servicios ejecute: scripts\stop_investai.bat" -ForegroundColor Gray
Write-Host "==========================================================" -ForegroundColor Green
