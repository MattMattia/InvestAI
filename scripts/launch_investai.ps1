# scripts/launch_investai.ps1
# InvestAI Enterprise - Orquestador de inicio con pantalla de carga nativa (sin consola).
# Se ejecuta oculto desde scripts\launch_silent.vbs; todo el feedback va a la ventana Splash
# y el detalle a %LOCALAPPDATA%\InvestAI\logs.
# Archivo ASCII puro: Windows PowerShell 5.1 lee los .ps1 sin BOM como ANSI.

param(
    # Muestra la pantalla de carga recorriendo las etapas sin tocar procesos ni puertos.
    [switch]$Preview
)

$ErrorActionPreference = 'Stop'

$rootDir = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location -LiteralPath $rootDir

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
. (Join-Path $PSScriptRoot 'investai_branding.ps1')
[System.Windows.Forms.Application]::EnableVisualStyles()

# --- Registro en disco (la consola esta oculta) ---------------------------------------
$logDir = Join-Path $env:LOCALAPPDATA 'InvestAI\logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$launcherLog = Join-Path $logDir 'launcher.log'
$backendLog = Join-Path $logDir 'backend.log'
$frontendLog = Join-Path $logDir 'frontend.log'

function Write-LauncherLog {
    param([string]$Message)
    Add-Content -LiteralPath $launcherLog -Value "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $Message" -Encoding UTF8
}

# --- Ventana Splash institucional -----------------------------------------------------
$colorBackground = [System.Drawing.ColorTranslator]::FromHtml('#0B0F19')
$colorBorder = [System.Drawing.ColorTranslator]::FromHtml('#0284C7')
$colorCyan = [System.Drawing.ColorTranslator]::FromHtml('#0EA5E9')
$colorEmerald = [System.Drawing.ColorTranslator]::FromHtml('#10B981')
$colorRed = [System.Drawing.ColorTranslator]::FromHtml('#EF4444')
$colorTrack = [System.Drawing.ColorTranslator]::FromHtml('#1E293B')
$colorMuted = [System.Drawing.ColorTranslator]::FromHtml('#94A3B8')
$colorStatus = [System.Drawing.ColorTranslator]::FromHtml('#7DD3FC')
$emDash = [char]0x2014

$splashForm = New-Object System.Windows.Forms.Form
$splashForm.Text = 'InvestAI Enterprise'
$splashForm.FormBorderStyle = 'None'
$splashForm.StartPosition = 'CenterScreen'
$splashForm.TopMost = $true
$splashForm.ShowInTaskbar = $true
$splashForm.Size = New-Object System.Drawing.Size(540, 320)
$splashForm.BackColor = $colorBorder
$splashForm.Padding = New-Object System.Windows.Forms.Padding(2)

$content = New-Object System.Windows.Forms.Panel
$content.Dock = 'Fill'
$content.BackColor = $colorBackground
$splashForm.Controls.Add($content)

$logoBox = New-Object System.Windows.Forms.PictureBox
$logoBox.Size = New-Object System.Drawing.Size(72, 72)
$logoBox.Location = New-Object System.Drawing.Point(232, 34)
$logoBox.SizeMode = 'Zoom'
$logoBox.BackColor = $colorBackground
$logoBox.Image = New-InvestAILogoBitmap -Size 144
$content.Controls.Add($logoBox)

$lblTitle = New-Object System.Windows.Forms.Label
$lblTitle.Text = 'INVESTAI ENTERPRISE'
$lblTitle.Font = New-Object System.Drawing.Font('Segoe UI', 18, [System.Drawing.FontStyle]::Bold)
$lblTitle.ForeColor = [System.Drawing.Color]::White
$lblTitle.TextAlign = 'MiddleCenter'
$lblTitle.Location = New-Object System.Drawing.Point(20, 120)
$lblTitle.Size = New-Object System.Drawing.Size(496, 38)
$content.Controls.Add($lblTitle)

$lblSubtitle = New-Object System.Windows.Forms.Label
$lblSubtitle.Text = "MOTOR CUANTITATIVO DE PORTAFOLIOS Y RIESGO DETERMINISTA $emDash BYMA"
$lblSubtitle.Font = New-Object System.Drawing.Font('Segoe UI', 8)
$lblSubtitle.ForeColor = $colorMuted
$lblSubtitle.TextAlign = 'MiddleCenter'
$lblSubtitle.Location = New-Object System.Drawing.Point(20, 160)
$lblSubtitle.Size = New-Object System.Drawing.Size(496, 20)
$content.Controls.Add($lblSubtitle)

$progressTrack = New-Object System.Windows.Forms.Panel
$progressTrack.Location = New-Object System.Drawing.Point(48, 208)
$progressTrack.Size = New-Object System.Drawing.Size(440, 6)
$progressTrack.BackColor = $colorTrack
$content.Controls.Add($progressTrack)

$progressFill = New-Object System.Windows.Forms.Panel
$progressFill.Location = New-Object System.Drawing.Point(0, 0)
$progressFill.Size = New-Object System.Drawing.Size(0, 6)
$progressFill.BackColor = $colorCyan
$progressTrack.Controls.Add($progressFill)

$lblStatus = New-Object System.Windows.Forms.Label
$lblStatus.Text = 'Iniciando...'
$lblStatus.Font = New-Object System.Drawing.Font('Segoe UI', 9)
$lblStatus.ForeColor = $colorStatus
$lblStatus.TextAlign = 'MiddleCenter'
$lblStatus.Location = New-Object System.Drawing.Point(20, 224)
$lblStatus.Size = New-Object System.Drawing.Size(496, 40)
$content.Controls.Add($lblStatus)

function Set-SplashStage {
    param([int]$Percent, [string]$Message)
    $lblStatus.Text = "[$Percent%] $Message"
    $progressFill.Width = [int]($progressTrack.Width * $Percent / 100)
    if ($Percent -ge 100) { $progressFill.BackColor = $colorEmerald }
    $splashForm.Refresh()
    [System.Windows.Forms.Application]::DoEvents()
    Write-LauncherLog "[$Percent%] $Message"
}

function Wait-WithUi {
    # Espera sin congelar la ventana: sigue atendiendo el bucle de mensajes.
    param([int]$Milliseconds)
    $deadline = [DateTime]::UtcNow.AddMilliseconds($Milliseconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        [System.Windows.Forms.Application]::DoEvents()
        Start-Sleep -Milliseconds 25
    }
}

function Wait-ProcessWithUi {
    param($Process, [int]$TimeoutSeconds)
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while (-not $Process.HasExited -and [DateTime]::UtcNow -lt $deadline) {
        [System.Windows.Forms.Application]::DoEvents()
        Start-Sleep -Milliseconds 50
    }
    return $Process.HasExited
}

function Test-TcpPortOpen {
    param(
        [string]$HostName = '127.0.0.1',
        [int]$Port,
        [int]$TimeoutMs = 200
    )
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $iar = $client.BeginConnect($HostName, $Port, $null, $null)
        $connected = $iar.AsyncWaitHandle.WaitOne($TimeoutMs, $false)
        if (-not $connected) { return $false }
        $client.EndConnect($iar)
        return $true
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

function Test-HttpOk {
    param([string]$Uri)
    try {
        $response = Invoke-WebRequest -Uri $Uri -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
        return ($response.StatusCode -eq 200)
    } catch {
        return $false
    }
}

function Show-SplashFailure {
    # Sin consola visible, una falla tiene que quedar a la vista y no cerrarse sola.
    param([string]$Message)
    Write-LauncherLog "ERROR: $Message"
    $lblStatus.ForeColor = $colorRed
    $lblStatus.Text = "$Message`r`nDetalle: $logDir"
    $progressFill.BackColor = $colorRed
    $progressFill.Width = $progressTrack.Width

    $btnLogs = New-Object System.Windows.Forms.Button
    $btnLogs.Text = 'Ver registros'
    $btnLogs.FlatStyle = 'Flat'
    $btnLogs.ForeColor = [System.Drawing.Color]::White
    $btnLogs.BackColor = $colorTrack
    $btnLogs.Size = New-Object System.Drawing.Size(120, 28)
    $btnLogs.Location = New-Object System.Drawing.Point(142, 272)
    $btnLogs.Add_Click({ Start-Process explorer.exe -ArgumentList "`"$logDir`"" })
    $content.Controls.Add($btnLogs)

    $btnClose = New-Object System.Windows.Forms.Button
    $btnClose.Text = 'Cerrar'
    $btnClose.FlatStyle = 'Flat'
    $btnClose.ForeColor = [System.Drawing.Color]::White
    $btnClose.BackColor = $colorTrack
    $btnClose.Size = New-Object System.Drawing.Size(120, 28)
    $btnClose.Location = New-Object System.Drawing.Point(274, 272)
    $btnClose.Add_Click({ $splashForm.Close() })
    $content.Controls.Add($btnClose)

    $splashForm.TopMost = $false
    $splashForm.Refresh()
    while ($splashForm.Visible) {
        [System.Windows.Forms.Application]::DoEvents()
        Start-Sleep -Milliseconds 50
    }
}

$stageStop = 'Deteniendo instancias previas y liberando puertos 8000 / 5173...'
$stageSeed = 'Verificando base de datos e inicializando semilla institucional...'
$stageServers = 'Iniciando servidor FastAPI (8000) y entorno Vite (5173)...'
$stageWarm = 'Pre-calentando cotizaciones BYMA en vivo (Yahoo Finance / BCBA)...'
$stageReady = "$([char]0x00A1)Sistema listo! Abriendo InvestAI Enterprise..."

$exitCode = 0
try {
    $splashForm.Show()
    $splashForm.Refresh()
    [System.Windows.Forms.Application]::DoEvents()
    Write-LauncherLog "---- Inicio del launcher (root: $rootDir, preview: $($Preview.IsPresent)) ----"

    if ($Preview) {
        foreach ($stage in @(@(15, $stageStop), @(35, $stageSeed), @(60, $stageServers), @(85, $stageWarm), @(100, $stageReady))) {
            Set-SplashStage -Percent $stage[0] -Message $stage[1]
            Wait-WithUi -Milliseconds 700
        }
        exit 0
    }

    # 1. Detener instancias previas preventivamente
    Set-SplashStage -Percent 15 -Message $stageStop
    $stopScript = Join-Path $PSScriptRoot 'stop_investai.ps1'
    if (Test-Path $stopScript) {
        $stopProc = Start-Process -FilePath 'powershell.exe' -ArgumentList '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$stopScript`"" -WindowStyle Hidden -PassThru
        [void](Wait-ProcessWithUi -Process $stopProc -TimeoutSeconds 20)
    }

    # 2. Detectar ejecutable de Python
    $venvPython = Join-Path $rootDir '.venv\Scripts\python.exe'
    $localAppPython = "$env:LOCALAPPDATA\Python\bin\python.exe"
    if (Test-Path $venvPython) {
        $pythonCmd = $venvPython
    } elseif (Test-Path $localAppPython) {
        $pythonCmd = $localAppPython
    } else {
        $cmdPython = (Get-Command 'python.exe' -ErrorAction SilentlyContinue)
        if ($cmdPython) { $pythonCmd = $cmdPython.Source } else { $pythonCmd = 'python' }
    }
    Write-LauncherLog "Python: $pythonCmd"

    # 3. PYTHONPATH para backend y semilla de demostracion (oculta, sin bloquear la ventana)
    $env:PYTHONPATH = Join-Path $rootDir 'backend'
    Set-SplashStage -Percent 35 -Message $stageSeed
    $seedScript = Join-Path $rootDir 'backend\scripts\seed_smoke_test.py'
    $seedProc = Start-Process -FilePath $pythonCmd -ArgumentList "`"$seedScript`"" -WindowStyle Hidden -PassThru
    if (Wait-ProcessWithUi -Process $seedProc -TimeoutSeconds 120) {
        Write-LauncherLog "Semilla finalizada con codigo $($seedProc.ExitCode)"
    } else {
        Write-LauncherLog 'Semilla sin finalizar tras 120s; se continua con el arranque'
    }

    # 4. Backend FastAPI y Frontend Vite en paralelo, ocultos y con salida a archivos de log
    Set-SplashStage -Percent 60 -Message $stageServers
    $backendCommand = "/c `"`"$pythonCmd`" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 > `"$backendLog`" 2>&1`""
    $frontendCommand = "/c `"npm --prefix frontend run dev -- --host 127.0.0.1 --port 5173 --strictPort > `"$frontendLog`" 2>&1`""
    $backendProc = Start-Process -FilePath 'cmd.exe' -ArgumentList $backendCommand -WindowStyle Hidden -PassThru
    $frontendProc = Start-Process -FilePath 'cmd.exe' -ArgumentList $frontendCommand -WindowStyle Hidden -PassThru
    Write-LauncherLog "Backend PID $($backendProc.Id), Frontend PID $($frontendProc.Id)"

    # 5. Healthcheck reactivo (200 ms) del backend y luego del frontend
    Set-SplashStage -Percent 85 -Message $stageWarm
    $backendHealthy = $false
    $deadline = [DateTime]::UtcNow.AddSeconds(60)
    while ([DateTime]::UtcNow -lt $deadline) {
        Wait-WithUi -Milliseconds 200
        if (Test-HttpOk -Uri 'http://127.0.0.1:8000/health') { $backendHealthy = $true; break }
        if ($backendProc.HasExited) { break }
    }
    if (-not $backendHealthy) {
        Show-SplashFailure -Message 'El servidor FastAPI (8000) no pudo iniciar.'
        exit 1
    }

    $frontendReady = $false
    $deadline = [DateTime]::UtcNow.AddSeconds(45)
    while ([DateTime]::UtcNow -lt $deadline) {
        if (Test-TcpPortOpen -HostName '127.0.0.1' -Port 5173 -TimeoutMs 200) {
            if (Test-HttpOk -Uri 'http://127.0.0.1:5173') { $frontendReady = $true; break }
        }
        if ($frontendProc.HasExited) { break }
        Wait-WithUi -Milliseconds 150
    }
    if (-not $frontendReady) {
        Show-SplashFailure -Message 'El entorno Vite (5173) no pudo iniciar.'
        exit 1
    }

    # 6. Lanzamiento en modo aplicacion de escritorio
    Set-SplashStage -Percent 100 -Message $stageReady
    $candidateBrowsers = @(
        'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
        'C:\Program Files\Microsoft\Edge\Application\msedge.exe',
        'C:\Program Files\Google\Chrome\Application\chrome.exe'
    )
    $selectedBrowser = $candidateBrowsers | Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($selectedBrowser) {
        Start-Process -FilePath $selectedBrowser -ArgumentList '--app=http://localhost:5173', '--window-size=1440,900' | Out-Null
    } else {
        Start-Process 'http://localhost:5173'
    }
    Write-LauncherLog 'Aplicacion abierta. Para detener servicios: scripts\stop_investai.bat'
    Wait-WithUi -Milliseconds 800
} catch {
    $exitCode = 1
    Show-SplashFailure -Message "Error inesperado del launcher: $($_.Exception.Message)"
} finally {
    if ($splashForm.Visible) { $splashForm.Close() }
    if ($logoBox.Image) { $logoBox.Image.Dispose() }
    $splashForm.Dispose()
}
exit $exitCode
