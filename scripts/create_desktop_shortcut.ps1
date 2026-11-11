# scripts/create_desktop_shortcut.ps1
# InvestAI Enterprise - Generador de Acceso Directo de Escritorio (sin consola)
# El acceso directo ejecuta wscript.exe con scripts\launch_silent.vbs, por lo que el doble
# clic nunca abre una ventana CMD: solo se ve la pantalla de carga de InvestAI.
# Archivo ASCII puro: Windows PowerShell 5.1 lee los .ps1 sin BOM como ANSI.

param(
    # Genera unicamente frontend\public\investai.ico, sin crear el acceso directo.
    [switch]$IconOnly
)

$ErrorActionPreference = 'Stop'

$rootDir = (Resolve-Path "$PSScriptRoot\..").Path
. (Join-Path $PSScriptRoot 'investai_branding.ps1')

# 1. Icono institucional generado a partir del isotipo vectorial
$iconPath = Join-Path $rootDir 'frontend\public\investai.ico'
try {
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $iconPath) | Out-Null
    New-InvestAIIconFile -Path $iconPath
    Write-Host "[InvestAI] Icono institucional generado: $iconPath" -ForegroundColor Gray
} catch {
    Write-Warning "[InvestAI] No se pudo generar el icono ($($_.Exception.Message)). Se usa el icono por defecto."
    $iconPath = $null
}

if ($IconOnly) { return }

# 2. Acceso directo: wscript.exe + lanzador silencioso
$desktopPath = [Environment]::GetFolderPath('Desktop')
$launcherVbs = Join-Path $rootDir 'scripts\launch_silent.vbs'
$wscriptExe = Join-Path $env:SystemRoot 'System32\wscript.exe'
$shortcutPath = Join-Path $desktopPath 'InvestAI Enterprise.lnk'

Write-Host '[InvestAI] Creando acceso directo en el Escritorio...' -ForegroundColor Cyan
Write-Host "  -> Lanzador silencioso: $launcherVbs" -ForegroundColor Gray
Write-Host "  -> Ubicacion acceso directo: $shortcutPath" -ForegroundColor Gray

$WshShell = New-Object -ComObject WScript.Shell
$shortcut = $WshShell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $wscriptExe
$shortcut.Arguments = "//B //NoLogo `"$launcherVbs`""
$shortcut.WorkingDirectory = $rootDir
$shortcut.WindowStyle = 7
$shortcut.Description = 'InvestAI Enterprise - Plataforma Cuantitativa y Gestion de Carteras'
if ($iconPath) {
    $shortcut.IconLocation = "$iconPath,0"
}

# Guardar acceso directo en el escritorio
$shortcut.Save()

Write-Host "[InvestAI] Acceso directo 'InvestAI Enterprise.lnk' creado exitosamente en el Escritorio de Windows." -ForegroundColor Green
