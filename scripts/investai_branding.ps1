# scripts/investai_branding.ps1
# InvestAI Enterprise - Isotipo institucional compartido por el launcher y el acceso directo.
# Dibuja el mismo escudo octogonal del frontend (InvestAILogo.tsx) con GDI+.
# Archivo ASCII puro: Windows PowerShell 5.1 lee los .ps1 sin BOM como ANSI.

Add-Type -AssemblyName System.Drawing

function New-InvestAILogoBitmap {
    param([int]$Size = 256)

    $bitmap = New-Object System.Drawing.Bitmap($Size, $Size, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    try {
        $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
        $graphics.Clear([System.Drawing.Color]::Transparent)
        $scale = $Size / 48.0

        # Escudo octogonal con gradiente #0284C7 -> #10B981 -> #6366F1
        $coords = @(17, 5, 31, 5, 43, 17, 43, 31, 31, 43, 17, 43, 5, 31, 5, 17)
        $points = New-Object 'System.Collections.Generic.List[System.Drawing.PointF]'
        for ($i = 0; $i -lt $coords.Count; $i += 2) {
            $points.Add((New-Object System.Drawing.PointF([single]($coords[$i] * $scale), [single]($coords[$i + 1] * $scale))))
        }
        $bounds = New-Object System.Drawing.RectangleF(0, 0, $Size, $Size)
        $gradient = New-Object System.Drawing.Drawing2D.LinearGradientBrush($bounds, [System.Drawing.Color]::Black, [System.Drawing.Color]::Black, [single]45.0)
        $blend = New-Object System.Drawing.Drawing2D.ColorBlend(3)
        $blend.Colors = @(
            [System.Drawing.ColorTranslator]::FromHtml('#0284C7'),
            [System.Drawing.ColorTranslator]::FromHtml('#10B981'),
            [System.Drawing.ColorTranslator]::FromHtml('#6366F1')
        )
        $blend.Positions = [single[]]@(0.0, 0.55, 1.0)
        $gradient.InterpolationColors = $blend
        $graphics.FillPolygon($gradient, $points.ToArray())

        # Barras ascendentes de precision
        $white = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(235, 255, 255, 255))
        foreach ($bar in @(@(13, 28, 7), @(20, 24, 11), @(27, 20, 15))) {
            $graphics.FillRectangle($white, [single]($bar[0] * $scale), [single]($bar[1] * $scale), [single](4.5 * $scale), [single]($bar[2] * $scale))
        }

        # Frontera eficiente de Markowitz con nodo optimo
        $pen = New-Object System.Drawing.Pen([System.Drawing.Color]::White, [single](2 * $scale))
        $pen.StartCap = [System.Drawing.Drawing2D.LineCap]::Round
        $pen.EndCap = [System.Drawing.Drawing2D.LineCap]::Round
        $graphics.DrawBezier(
            $pen,
            [single](11 * $scale), [single](29 * $scale),
            [single](14 * $scale), [single](17 * $scale),
            [single](24 * $scale), [single](12.5 * $scale),
            [single](35 * $scale), [single](13 * $scale)
        )
        $graphics.FillEllipse($white, [single](32.4 * $scale), [single](10.4 * $scale), [single](5.2 * $scale), [single](5.2 * $scale))

        $pen.Dispose()
        $white.Dispose()
        $gradient.Dispose()
    } finally {
        $graphics.Dispose()
    }
    return $bitmap
}

function New-InvestAIIconFile {
    # Escribe un .ico de 256x256 con payload PNG (formato soportado desde Windows Vista).
    param([Parameter(Mandatory = $true)][string]$Path)

    $bitmap = New-InvestAILogoBitmap -Size 256
    $pngStream = New-Object System.IO.MemoryStream
    try {
        $bitmap.Save($pngStream, [System.Drawing.Imaging.ImageFormat]::Png)
        $png = $pngStream.ToArray()
    } finally {
        $pngStream.Dispose()
        $bitmap.Dispose()
    }

    $file = [System.IO.File]::Create($Path)
    $writer = New-Object System.IO.BinaryWriter($file)
    try {
        # ICONDIR: reservado, tipo 1 (icono), 1 imagen
        $writer.Write([uint16]0)
        $writer.Write([uint16]1)
        $writer.Write([uint16]1)
        # ICONDIRENTRY: ancho/alto 0 = 256 px, sin paleta, 1 plano, 32 bpp
        $writer.Write([byte]0)
        $writer.Write([byte]0)
        $writer.Write([byte]0)
        $writer.Write([byte]0)
        $writer.Write([uint16]1)
        $writer.Write([uint16]32)
        $writer.Write([uint32]$png.Length)
        $writer.Write([uint32]22)
        $writer.Write([byte[]]$png)
    } finally {
        $writer.Dispose()
        $file.Dispose()
    }
}
