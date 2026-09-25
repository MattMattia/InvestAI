# InvestAI — PowerShell Launcher con Diagnóstico y Apagado Limpio (Graceful Shutdown)
$ErrorActionPreference = "Stop"

Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "         InvestAI — Plataforma de Riesgo Financiero    " -ForegroundColor Cyan
Write-Host "             Iniciador One-Click Local (PowerShell)     " -ForegroundColor Cyan
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host ""

# 1. Verificar prerrequisitos
try {
    $pythonVersion = python --version 2>&1
    Write-Host "[OK] Python detectado: $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "[ERROR CRITICO] Python no encontrado en el PATH." -ForegroundColor Red
    exit 1
}

try {
    $nodeVersion = node --version 2>&1
    Write-Host "[OK] Node.js detectado: $nodeVersion" -ForegroundColor Green
} catch {
    Write-Host "[ERROR CRITICO] Node.js no encontrado en el PATH." -ForegroundColor Red
    exit 1
}

Write-Host ""

# 2. Diagnostico y liberacion de puertos locales (8000 y 5173)
Write-Host "[Diagnostico] Verificando puertos 8000 y 5173..." -ForegroundColor Yellow
Get-NetTCPConnection -LocalPort 8000, 5173 -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
    Write-Host "[INFO] Liberando puerto $($_.LocalPort) ocupado por PID $($_.OwningProcess)..." -ForegroundColor Yellow
    Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue
}

# Comprobar si hay contenedores Docker mapeando los puertos
try {
    $dockers8000 = docker ps -q --filter "publish=8000" 2>$null
    if ($dockers8000) {
        Write-Host "[INFO] Deteniendo contenedor Docker que bloqueaba el puerto 8000 ($dockers8000)..." -ForegroundColor Yellow
        docker stop $dockers8000 2>$null
    }
} catch {}

$backendDir = Join-Path $PSScriptRoot "backend"
$frontendDir = Join-Path $PSScriptRoot "frontend"

# 3. Iniciar Backend FastAPI
Write-Host "[1/3] Iniciando Backend FastAPI en http://127.0.0.1:8000..." -ForegroundColor Yellow
$backendProcess = Start-Process -FilePath "python" `
    -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000", "--reload" `
    -WorkingDirectory $backendDir `
    -Environment @{ PYTHONPATH = $backendDir } `
    -PassThru

# Breve espera para inicializacion
Start-Sleep -Seconds 3

# 4. Iniciar Frontend Vite
Write-Host "[2/3] Iniciando Frontend Vite en http://127.0.0.1:5173..." -ForegroundColor Yellow
$frontendProcess = Start-Process -FilePath "npm.cmd" `
    -ArgumentList "run", "dev", "--", "--host", "127.0.0.1", "--port", "5173" `
    -WorkingDirectory $frontendDir `
    -PassThru

Start-Sleep -Seconds 2

# 5. Abrir Navegador
Write-Host "[3/3] Abriendo navegador predeterminado..." -ForegroundColor Yellow
Start-Process "http://127.0.0.1:5173"

Write-Host ""
Write-Host "========================================================" -ForegroundColor Green
Write-Host "  InvestAI esta corriendo exitosamente:                " -ForegroundColor Green
Write-Host "    - Frontend: http://127.0.0.1:5173                  " -ForegroundColor White
Write-Host "    - Backend:  http://127.0.0.1:8000                  " -ForegroundColor White
Write-Host "    - API Docs: http://127.0.0.1:8000/docs             " -ForegroundColor White
Write-Host ""
Write-Host "  Presiona [Ctrl+C] en esta ventana para detener todos " -ForegroundColor Cyan
Write-Host "  los procesos ordenadamente.                          " -ForegroundColor Cyan
Write-Host "========================================================" -ForegroundColor Green

# 6. Gestion de apagado limpio
try {
    while ($true) {
        Start-Sleep -Seconds 1
        if ($backendProcess.HasExited -or $frontendProcess.HasExited) {
            break
        }
    }
} finally {
    Write-Host "`nDeteniendo servicios de InvestAI..." -ForegroundColor Yellow
    if ($backendProcess -and -not $backendProcess.HasExited) {
        Stop-Process -Id $backendProcess.Id -Force -ErrorAction SilentlyContinue
    }
    if ($frontendProcess -and -not $frontendProcess.HasExited) {
        taskkill /PID $frontendProcess.Id /T /F 2>$null
    }
    Write-Host "Servicios detenidos correctamente." -ForegroundColor Green
}
