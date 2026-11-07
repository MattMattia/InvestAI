@echo off
title InvestAI Launcher
color 0B
echo ========================================================
echo          InvestAI - Plataforma de Riesgo Financiero
echo                  Iniciador One-Click Local
echo ========================================================
echo.

:: 1. Verificar Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR CRITICO] Python no esta instalado o no se encuentra en el PATH.
    echo Por favor instala Python 3.11+ para continuar.
    echo.
    pause
    exit /b 1
)

:: 2. Verificar Node.js
node --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR CRITICO] Node.js no esta instalado o no se encuentra en el PATH.
    echo Por favor instala Node.js 18+ para continuar.
    echo.
    pause
    exit /b 1
)

echo [OK] Entornos de ejecucion detectados correctamente.
echo.

:: 3. Diagnostico y liberacion de puertos 8000 y 5173
echo [Diagnostico] Verificando disponibilidad de puertos 8000 y 5173...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8000 ^| findstr LISTENING 2^>nul') do (
    echo [AVISO] Liberando puerto 8000 ocupado previamente por PID %%a...
    taskkill /f /pid %%a >nul 2>&1
)

for /f "tokens=5" %%a in ('netstat -aon ^| findstr :5173 ^| findstr LISTENING 2^>nul') do (
    echo [AVISO] Liberando puerto 5173 ocupado previamente por PID %%a...
    taskkill /f /pid %%a >nul 2>&1
)

:: Detener contenedores Docker que pudieran estar usando el puerto 8000
for /f "tokens=*" %%c in ('docker ps -q --filter "publish=8000" 2^>nul') do (
    echo [AVISO] Deteniendo contenedor Docker %%c en conflicto con puerto 8000...
    docker stop %%c >nul 2>&1
)

echo [OK] Puertos listos para enlace local en 127.0.0.1.
echo.

:: 4. Iniciar Backend FastAPI con Uvicorn en 127.0.0.1:8000
echo [1/3] Iniciando Backend FastAPI (http://127.0.0.1:8000)...
start "InvestAI Backend (FastAPI)" cmd /k "set PYTHONPATH=%~dp0backend && cd /d %~dp0backend && python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload || (echo. && echo ======================================================== && echo [ERROR CRITICO] El Backend FastAPI fallo al iniciar. && echo Revisa el mensaje de error anterior para depurar. && echo ======================================================== && echo. && pause)"

:: Esperar a que el backend inicialice las tablas
timeout /t 3 /nobreak >nul

:: 5. Iniciar Frontend Vite (React + TypeScript) en 127.0.0.1:5173
echo [2/3] Iniciando Frontend Vite (http://127.0.0.1:5173)...
start "InvestAI Frontend (Vite)" cmd /k "cd /d %~dp0frontend && npm run dev -- --host 127.0.0.1 --port 5173 || (echo. && echo ======================================================== && echo [ERROR CRITICO] El Frontend fallo al iniciar. && echo ======================================================== && echo. && pause)"

:: Esperar inicio de Vite
timeout /t 2 /nobreak >nul

:: 6. Abrir Navegador
echo [3/3] Abriendo navegador en http://127.0.0.1:5173...
start http://127.0.0.1:5173

echo.
echo ========================================================
echo   InvestAI esta corriendo exitosamente:
echo     - Frontend: http://127.0.0.1:5173
echo     - Backend:  http://127.0.0.1:8000
echo     - API Docs: http://127.0.0.1:8000/docs
echo.
echo   Para detener los servicios, simplemente cierra las
echo   ventanas de consola del Backend y Frontend.
echo ========================================================
echo.
pause
