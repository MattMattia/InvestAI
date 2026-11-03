# scripts/launch_investai.ps1
# InvestAI Enterprise - Orquestador de Inicio y Lanzador de Aplicacion de Escritorio

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
    Write-Host "[InvestAI] Ejecutando limpieza preventiva de puertos..." -ForegroundColor Gray
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
Write-Host "[InvestAI] Interprete Python detectado: $pythonCmd" -ForegroundColor Gray

# 4. Configurar PYTHONPATH para backend
$backendDir = Join-Path $rootDir "backend"
$env:PYTHONPATH = $backendDir

# 5. Ejecutar la semilla de demostracion (smoke test)
Write-Host "[InvestAI] Ejecutando semilla de demostracion..." -ForegroundColor Cyan
$seedScript = Join-Path $rootDir "backend\scripts\seed_smoke_test.py"
& $pythonCmd $seedScript
if ($LASTEXITCODE -ne 0) {
    Write-Warning "[InvestAI] Advertencia: La semilla reporto codigo de salida $LASTEXITCODE."
} else {
    Write-Host "[InvestAI] Semilla de demostracion verificada con exito." -ForegroundColor Green
}

# 6. Lanzar Backend FastAPI en segundo plano
Write-Host "[InvestAI] Iniciando backend FastAPI en http://127.0.0.1:8000..." -ForegroundColor Cyan
Start-Process -FilePath $pythonCmd -ArgumentList "-m uvicorn app.main:app --host 127.0.0.1 --port 8000" -WindowStyle Hidden

# 7. Lanzar Frontend Vite en segundo plano con puerto estricto
Write-Host "[InvestAI] Iniciando frontend Vite en http://localhost:5173..." -ForegroundColor Cyan
Start-Process -FilePath "cmd.exe" -ArgumentList "/c npm --prefix frontend run dev -- --port 5173 --strictPort" -WindowStyle Hidden

# 8. Bucle reactivo de espera (Healthcheck)
Write-Host "[InvestAI] Esperando a que el backend este saludable (http://127.0.0.1:8000/health)..." -ForegroundColor Yellow
$maxAttempts = 60 # 60 intentos * 500ms = 30 segundos
$attempt = 0
$healthy = $false

while ($attempt -lt $maxAttempts) {
    Start-Sleep -Milliseconds 500
    $attempt++
    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:8000/health" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
        if ($response.StatusCode -eq 200) {
            $healthy = $true
            Write-Host "[InvestAI] Backend FastAPI en linea y saludable (intento $attempt - 200 OK)." -ForegroundColor Green
            break
        }
    } catch {
        # Reintentar en el siguiente ciclo
    }
}

if (-not $healthy) {
    Write-Warning "[InvestAI] Tiempo de espera de healthcheck agotado (30s). Continuando lanzamiento..."
}

# 9. Lanzamiento en Modo Aplicacion de Escritorio
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
    Write-Host "  -> Modo Standalone Desktop App via: $selectedBrowser" -ForegroundColor Gray
    Start-Process -FilePath $selectedBrowser -ArgumentList "--app=http://localhost:5173", "--window-size=1440,900"
} else {
    Write-Host "  -> Abriendo en navegador predeterminado..." -ForegroundColor Gray
    Start-Process "http://localhost:5173"
}

Write-Host "==========================================================" -ForegroundColor Green
Write-Host "   INVESTAI ENTERPRISE INICIADO EXITOSAMENTE" -ForegroundColor Green
Write-Host "   Credenciales demo: demo@investai.com / InvestAI2026!" -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Green
