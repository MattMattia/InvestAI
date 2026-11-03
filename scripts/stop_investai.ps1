# scripts/stop_investai.ps1
# InvestAI Enterprise - Script de Parada Limpia y Cierre de Puertos (8000 y 5173)

$ErrorActionPreference = 'SilentlyContinue'
$ports = @(8000, 5173)

Write-Host "[InvestAI] Verificando y liberando puertos $ports..." -ForegroundColor Cyan

foreach ($port in $ports) {
    try {
        $connections = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
        if ($connections) {
            $pidsToKill = $connections | Select-Object -ExpandProperty OwningProcess -Unique | Where-Object { $_ -gt 0 -and $_ -ne $PID }
            foreach ($procId in $pidsToKill) {
                try {
                    $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
                    if ($proc) {
                        Write-Host "  -> Deteniendo proceso $($proc.ProcessName) (PID: $procId) en puerto $port..." -ForegroundColor Yellow
                        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
                    }
                } catch {
                    # Ignorar si el proceso ya termino
                }
            }
        } else {
            Write-Host "  -> Puerto $port ya se encuentra libre." -ForegroundColor Green
        }
    } catch {
        # Ignorar excepciones de conexion
    }
}

Write-Host "[InvestAI] Limpieza de puertos finalizada con exito." -ForegroundColor Green
