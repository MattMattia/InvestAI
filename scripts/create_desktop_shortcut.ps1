# scripts/create_desktop_shortcut.ps1
# InvestAI Enterprise - Generador de Acceso Directo de Escritorio

$ErrorActionPreference = 'Stop'

$rootDir = (Resolve-Path "$PSScriptRoot\..").Path
$desktopPath = [Environment]::GetFolderPath("Desktop")
$targetBat = Join-Path $rootDir "start_investai.bat"
$shortcutPath = Join-Path $desktopPath "InvestAI Enterprise.lnk"

Write-Host "[InvestAI] Creando acceso directo en el Escritorio..." -ForegroundColor Cyan
Write-Host "  -> Archivo destino: $targetBat" -ForegroundColor Gray
Write-Host "  -> Ubicacion acceso directo: $shortcutPath" -ForegroundColor Gray

$WshShell = New-Object -ComObject WScript.Shell
$shortcut = $WshShell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $targetBat
$shortcut.WorkingDirectory = $rootDir
$shortcut.Description = "InvestAI Enterprise - Plataforma Cuantitativa y Gestion de Carteras"

# Guardar acceso directo en el escritorio
$shortcut.Save()

Write-Host "[InvestAI] Acceso directo 'InvestAI Enterprise.lnk' creado exitosamente en el Escritorio de Windows." -ForegroundColor Green
