# PROMPT DE EJECUCIÓN QUIRÚRGICA PARA CLAUDE FABLE 5.2 (HIGH)
## Remediación Integral de los 6 Hallazgos del Video de Prueba en Vivo — InvestAI Enterprise

---

## 0. DIRECTIVA DE ACTIVACIÓN DE SKILLS Y AGENTES (LOCALES + ECC)

Antes de inspeccionar o modificar cualquier archivo, activa y aplica los contratos de las siguientes **Skills instaladas en el entorno** (`.atl/skill-registry.md` / `~/.agents/skills/`):

1. **`desktop-app-architect`** (`C:\Users\risso\.agents\skills\desktop-app-architect\SKILL.md`)
   - *Ámbito*: Lanzador silencioso en Windows (`launch_silent.vbs`, `launch_investai.ps1`), ventana nativa WinForms Splash Screen sin consola CMD negra y acceso directo de escritorio (`create_desktop_shortcut.ps1`).
2. **`frontend-web-architect`** (`C:\Users\risso\.agents\skills\frontend-web-architect\SKILL.md`)
   - *Ámbito*: Arquitectura React 18 + TypeScript estricto, TanStack Query v5 (prefetching, eliminación de `initialData` engañoso, `placeholderData`, polling reactivo de 5s) y manejo de estado sin parpadeos.
3. **`frontend-design-architect`** (Estándar UI/UX Institucional Fintech + SVG Data Visualization)
   - *Ámbito*: Diseño del nuevo isotipo vectorial `InvestAILogo.tsx`, Splash Screen HTML/React con pulso cuántico, marcadores dinámicos de sesión en `FinancialTimeSeriesChart.tsx`, tarjetas sin truncamiento en `RebalancePanel.tsx` y botón ejecutivo en `MarketStatusBar.tsx`.
4. **`api-contract-fastapi`** (`C:\Users\risso\.agents\skills\api-contract-fastapi\SKILL.md`)
   - *Ámbito*: `lifespan` asíncrono con pre-warming en `backend/app/main.py`, enriquecimiento del contrato `/api/v1/market/live-quotes` con horario dinámico de mercado (`is_market_open`, `market_open_time`, `market_close_time`) y series intradiarias `1D` reales en `/api/v1/market/history/{ticker}`.
5. **`observability-metrics-tracing`** (`C:\Users\risso\.agents\skills\observability-metrics-tracing\SKILL.md`)
   - *Ámbito*: Telemetría de latencia y trazabilidad del motor de pre-calentamiento y sincronización de mercado en vivo.
6. **`secure-coding-hardened-systems`** (`C:\Users\risso\.agents\skills\secure-coding-hardened-systems\SKILL.md`)
   - *Ámbito*: Validación obligatoria de URLs salientes mediante `ssrf_checked_url` (`app/infrastructure/market_data/ssrf_guard.py`), timeouts estrictos y preservación de envoltorios `APIResponse` / `APIErrorResponse`.
7. **`adversarial-code-auditor`** & **`pytest-async-testsuite`** (`C:\Users\risso\.agents\skills\adversarial-code-auditor\SKILL.md`, `C:\Users\risso\.agents\skills\pytest-async-testsuite\SKILL.md`)
   - *Ámbito*: Garantía de cero regresiones sobre los **674 tests de backend** (`pytest backend/tests -q`), tipado estricto (`tsc --noEmit`) y formato limpio (`biome check`).

### Agentes / Patrones Especializados del Ecosistema ECC (Everything Claude Code) a Aplicar
- **`ecc:realtime-market-feed-architect`**: Patrón de *Server-Side Memory Pre-Warming + Monotonic Live State Ratchet* (los precios reales descargados de Yahoo Finance `.BA` / Google Finance `:BCBA` actualizan permanentemente el precio base en memoria y jamás revierten a semillas estáticas antiguas).
- **`ecc:svg-financial-chart-specialist`**: Renderizado condicional estricto por granularidad temporal (`timeframe === "1D"`) y anclaje exacto del primer punto (`regularMarketOpen`) y último punto (`last_price`).
- **`ecc:windows-zero-console-launcher`**: Ejecución mediante `wscript.exe` (`WScript.Shell.Run ..., 0, False`) combinada con ventana Splash nativa `System.Windows.Forms` sin bordes (`FormBorderStyle.None`) para eliminar al 100% la ventana negra de terminal.

---

## REGLAS DE ORO Y RESTRICCIONES ARQUITECTÓNICAS (CUMPLIMIENTO OBLIGATORIO)

1. **Prohibido crear archivos basura en la raíz**: No dejes scripts temporales (`test_*.py`, `check_*.py`, `*.tmp`) en la raíz del repositorio.
2. **Seguridad SSRF (`AGENTS.md`)**: Toda llamada HTTP saliente en `market_data_provider.py` DEBE pasar por `await ssrf_checked_url(url)`.
3. **Frontend TypeScript Estricto (`AGENTS.md`)**:
   - Cero uso de `any` explícito (usa tipos de `src/types/api.ts` o `unknown` con narrowing).
   - Todo elemento `<button>` debe declarar explícitamente `type="button"` (o `submit`).
   - Las keys de listas deben usar identificadores estables de dominio, nunca el índice del array.
4. **Tests y Compilación**:
   - Los **674 tests de backend** deben pasar al 100% (`pytest backend/tests -q`).
   - El build de producción de frontend (`npm --prefix frontend run build`) debe compilar con **0 errores**.
5. **No ejecutar `git commit`** a menos que el usuario lo pida explícitamente tras verificar los cambios.

---

## MAPA QUIRÚRGICO DE LOS 6 PROBLEMAS Y ESPECIFICACIONES LÍNEA POR LÍNEA

---

### PROBLEMA 1 (Video `00:05` - `00:20`): Reemplazar la Consola Negra de Inicio por una Pantalla de Carga (Splash Screen) Institucional de InvestAI

#### Causa Raíz Detectada
- `start_investai.bat` (líneas 1-5) invoca `powershell.exe` directamente desde un archivo por lotes `.bat`, lo que fuerza a Windows (`cmd.exe` / `conhost.exe`) a abrir una ventana de consola negra con texto plano durante 10-15 segundos.
- `scripts/create_desktop_shortcut.ps1` (líneas 8-22) apunta el acceso directo `InvestAI Enterprise.lnk` hacia `start_investai.bat` con estilo de ventana normal.

#### Archivos a Crear / Modificar

1. **Crear `scripts/launch_silent.vbs`** (Lanzador Nativo Cero-Consola para Windows):
   ```vbscript
   ' InvestAI Enterprise - Silent Zero-Console Launcher
   Option Explicit
   Dim objShell, objFSO, strRootDir, strPsScript, strCmd
   Set objFSO = CreateObject("Scripting.FileSystemObject")
   Set objShell = CreateObject("WScript.Shell")
   strRootDir = objFSO.GetParentFolderName(objFSO.GetParentFolderName(WScript.ScriptFullName))
   objShell.CurrentDirectory = strRootDir
   strPsScript = objFSO.BuildPath(strRootDir, "scripts\launch_investai.ps1")
   strCmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Sta -File """ & strPsScript & """"
   ' 0 = Hide window completely, False = Do not block WScript
   objShell.Run strCmd, 0, False
   ```

2. **Modificar `start_investai.bat` (líneas 1-5)**:
   - Hacer que `start_investai.bat` delegue inmediatamente en `wscript.exe //B //NoLogo "%~dp0scripts\launch_silent.vbs"` y termine en `< 10ms` para que incluso si el usuario ejecuta el `.bat` manualmente no permanezca ninguna consola abierta:
   ```bat
   @echo off
   start "" wscript.exe //B //NoLogo "%~dp0scripts\launch_silent.vbs"
   exit /b 0
   ```

3. **Modificar `scripts/launch_investai.ps1` (líneas 1-101)**:
   - Cargar `System.Windows.Forms` y `System.Drawing` al inicio del script para desplegar inmediatamente una **Ventana Splash Institucional Nativa (`FormBorderStyle = 'None'`, `StartPosition = 'CenterScreen'`, `TopMost = $true`, tamaño `540x320`, fondo oscuro `#0B0F19` con borde cian `#0284C7`)**.
   - La ventana Splash debe mostrar:
     - Título: **`INVESTAI ENTERPRISE`** y subtítulo **`MOTOR CUANTITATIVO DE PORTAFOLIOS Y RIESGO DETERMINISTA — BYMA`**.
     - Etiqueta de estado dinámica (`$lblStatus.Text`) que se actualiza en vivo en cada etapa con `$splashForm.Refresh()` / `[System.Windows.Forms.Application]::DoEvents()`:
       1. `[15%] Deteniendo instancias previas y liberando puertos 8000 / 5173...`
       2. `[35%] Verificando base de datos e inicializando semilla institucional...` (ejecutar `$seedScript` con `Start-Process ... -WindowStyle Hidden -Wait` para que no abra ventana).
       3. `[60%] Iniciando servidor FastAPI (8000) y entorno Vite (5173)...`
       4. `[85%] Pre-calentando cotizaciones BYMA en vivo (Yahoo Finance / BCBA)...` (durante el bucle de `/health` cada 200ms).
       5. `[100%] ¡Sistema listo! Abriendo InvestAI Enterprise...`
     - Barra de progreso visual personalizada (`Panel` contenedor + `Panel` de relleno en color cian `#0EA5E9` / esmeralda `#10B981`).
   - Al detectar `/health` HTTP 200 (y tras verificar que el puerto 5173 responde), abrir el navegador en modo `--app=http://localhost:5173`, esperar 800ms y cerrar limpiamente `$splashForm.Close()`.

4. **Modificar `scripts/create_desktop_shortcut.ps1` (líneas 8-22)**:
   - Configurar el acceso directo `InvestAI Enterprise.lnk` para que ejecute `wscript.exe` pasando como argumento `"//B //NoLogo ""$rootDir\scripts\launch_silent.vbs"""`, con `$shortcut.WindowStyle = 7` (minimizado/oculto) y un icono institucional `.ico` generado automáticamente en `frontend/public/investai.ico` (o el icono nativo de gráficos financieros del sistema), garantizando que el doble clic en el escritorio **jamás muestre una ventana CMD negra**.

5. **Modificar `frontend/index.html` (líneas 11-14)**:
   - Dentro de `<div id="root">`, incluir un **Splash Screen HTML/CSS instantáneo** con fondo `#020617`, el nuevo isotipo SVG de InvestAI Enterprise, animación de pulso cuántico y barra de carga indeterminada. Tan pronto como React monte `<App />`, reemplazará el contenido de `#root` sin parpadeo en blanco ni negro.

---

### PROBLEMA 2 (Video `00:40` - `00:55`): Actualización Instantánea (`< 1 segundo`) al Entrar al Monitor de Mercado (Sin Gráfico Verde Falso Inicial)

#### Causa Raíz Detectada
- En el video, al hacer clic en **"Mercado en Vivo"**, durante 3 segundos se muestra `GGAL` con el precio semilla viejo `$5.120,00 (+2.95%)` y una curva verde alcista sintética, y recién a los 3 segundos salta bruscamente al precio real `$4.976,40 (-14.71%)` con curva roja.
- Esto ocurre porque:
  1. `backend/app/main.py` (`lifespan`, líneas 27-35) no pre-calienta `PublicMarket10YProvider` al iniciar FastAPI, por lo que la primera petición a `/api/v1/market/live-quotes` y `/api/v1/market/history/GGAL` tarda ~2.5s en consultar Yahoo Finance.
  2. `frontend/src/components/market/MarketDataView.tsx` (líneas 124-130 y 140) inyectaba `initialData: () => ({ quotes: marketService.getCuratedQuotesSync(...) })` y `initialData: () => buildDeterministicHistoricalBars(...)`, forzando a React a dibujar datos semilla falsos antes de recibir la respuesta del backend.

#### Archivos y Líneas Exactas a Modificar

1. **`backend/app/domain/services/market_data_provider.py` (clase `PublicMarket10YProvider`, líneas 1514-1520)**:
   - Agregar caché en memoria de barras históricas y tarea de sincronización en segundo plano:
     ```python
     _BARS_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}
     _BG_TASK: asyncio.Task[None] | None = None
     ```
   - Implementar `@classmethod async def prewarm_and_loop(cls) -> None`:
     - En el arranque, ejecuta `await cls.fetch_live_quotes_batch(force_refresh=True)` y luego pre-carga en paralelo (`asyncio.gather`) `fetch_live_historical_bars(t, tf)` para `t in ("GGAL", "YPFD", "PAMP", "NVDA", "AAPL", "MELI", "SPY", "AL30")` y `tf in ("1D", "1M")`.
     - Luego mantiene un bucle `while True:` con `await asyncio.sleep(15.0)` que refresca silenciosamente las cotizaciones y series principales en segundo plano.

2. **`backend/app/main.py` (`lifespan`, líneas 27-35)**:
   - Iniciar la tarea de pre-calentamiento en el `lifespan` (excepto si la variable de entorno `TESTING=1` o durante pytest para no interferir con tests unitarios):
     ```python
     @asynccontextmanager
     async def lifespan(app: FastAPI):
         """Application lifespan context manager for startup and shutdown hooks."""
         await init_db()
         bg_task = None
         if settings.ENVIRONMENT.lower() != "test":
             from app.domain.services.market_data_provider import PublicMarket10YProvider
             bg_task = asyncio.create_task(PublicMarket10YProvider.prewarm_and_loop())
         try:
             yield
         finally:
             if bg_task is not None:
                 bg_task.cancel()
             await async_engine.dispose()
     ```

3. **`frontend/src/App.tsx` (al montar el componente principal)**:
   - Agregar un `useEffect` que pre-cargue en segundo plano en la caché de TanStack Query las cotizaciones y la serie de `GGAL` apenas abre la aplicación:
     ```tsx
     useEffect(() => {
       queryClient.prefetchQuery({
         queryKey: marketKeys.quotes("ALL"),
         queryFn: () => marketService.getLiveMarketFeed("ALL", false),
       });
       queryClient.prefetchQuery({
         queryKey: marketKeys.history("GGAL", "1M"),
         queryFn: () => marketService.getHistoricalBars("GGAL", "1M"),
       });
       queryClient.prefetchQuery({
         queryKey: marketKeys.history("GGAL", "1D"),
         queryFn: () => marketService.getHistoricalBars("GGAL", "1D"),
       });
     }, [queryClient]);
     ```

4. **`frontend/src/components/market/MarketDataView.tsx` (líneas 120-152)**:
   - **Eliminar `initialData`** tanto de `feedQuery` como de `historyQuery` para que **NUNCA se dibuje un precio semilla falso ni una curva verde falsa** al entrar a la vista o al cambiar de ticker.
   - Usar `placeholderData: (prev) => prev` y, mientras `historyQuery.isLoading` sea `true` y no haya datos reales para el `activeTicker`, mostrar un esqueleto institucional de carga ultrarrápido (`< 100ms` gracias al pre-warming) en lugar de `buildDeterministicHistoricalBars`.

---

### PROBLEMA 3 (Video `01:13` - `03:15`): Precio Real de `NVDA (CEDEAR)` (`~$12.180`), Precio de Apertura Real de Hoy (`$12.270` vs `$14.400` viejo) y Gráfico `1D` Intradiario Real

#### Causas Raíz Detectadas (3 Sub-bugs Críticos)
- **Bug 3A (Saltos locos cada 5s entre `$12.180` y `$14.211`)**:
  - En `BYMA_CURATED_UNIVERSE_CATALOG` (`market_data_provider.py` línea 1281) y `CURATED_INSTRUMENTS` (`marketService.ts` línea 92), `NVDA` tenía hardcodeado `target_price: 14290.0` (precio viejo del 3 de noviembre).
  - Cuando Yahoo Finance devolvía el precio real de hoy (`$12.180`), si en una consulta posterior ocurría un timeout o entraba el fallback de Google Finance (línea 1673: `prev_val = float(inst.get("target_price", last_val))`), o cuando `MarketDataView` caía en fallback en el frontend, el precio saltaba de `$12.180` a `$14.290` / `$14.211` y al siguiente tick volvía a `$12.180`.
- **Bug 3B (Primer punto del gráfico `1D` en `$14.400` en vez de `$12.270` de apertura de hoy)**:
  - En `fetch_live_historical_bars(ticker, "1D")` (líneas 1835-1912), el código NO consultaba Yahoo Finance para `1D`, sino que fabricaba una curva sintética partiendo de `previous_close` (que si venía contaminado por `14290.0` generaba un primer punto en `~$14.400`).
- **Bug 3C (Etiqueta `CIERRE 17:00 -> AFTER-HOURS` mostrándose en `1M`, `1W`, `1Y`)**:
  - En `market_data_provider.py` línea 1969, a las velas de `1W`, `1M` y `1Y` se les asignaba `raw_bars[-1]["is_market_open"] = is_now_open` (`False` después de las 17:00), lo cual activaba `transitionPoint` en `FinancialTimeSeriesChart.tsx` en todas las temporalidades.

#### Archivos y Líneas Exactas a Modificar

1. **Actualizar Precios Base de Respaldo y Implementar *Monotonic Live Price Ratchet* en `backend/app/domain/services/market_data_provider.py` y `frontend/src/services/marketService.ts`**:
   - Actualizar los `target_price` / `reference_price` de respaldo en `BYMA_CURATED_UNIVERSE_CATALOG` (líneas 1180-1411), `CALIBRATED_10Y_METRICS_CATALOG` (líneas 138-600), `backend/scripts/seed_smoke_test.py` y `frontend/src/services/marketService.ts` (líneas 77-109):
     - `NVDA`: `12180.0` (Apertura hoy: `12270.0`)
     - `GGAL`: `4980.0`
     - `YPFD`: `29850.0`
     - `PAMP`: `3390.0`
     - `AAPL`: `15120.0`
     - `MSFT`: `16400.0`
     - `MELI`: `27800.0`
     - `SPY`: `31150.0`
   - **Regla de Oro en `_fetch_single_instrument` (`market_data_provider.py` líneas 1603-1723)**:
     - Cuando Yahoo Finance `.BA` o Google Finance `:BCBA` devuelven un precio real `last_val > 0`:
       1. **Sobrescribir permanentemente en memoria** `inst["target_price"] = round(last_val, 2)` y `BYMA_CURATED_UNIVERSE_MAP[t]["target_price"] = round(last_val, 2)`.
       2. En Google Finance fallback (línea 1673), usar como `prev_val` el `previous_close` ya guardado en `cls._LIVE_STATE.get(t, {}).get("previous_close")` o `last_val` (¡jamás un `target_price` viejo distante!).
       3. Si tanto Yahoo como Google fallan por timeout puntual y `t in cls._LIVE_STATE`, **retornar `dict(cls._LIVE_STATE[t])`** conservando el último precio real en vivo en lugar de sobrescribirlo con semillas estáticas.
   - **Micro-Tick Realista de 5 Segundos (`market_data_provider.py` líneas 1772-1796)**:
     - Ajustar el ruido estocástico de 5 segundos a una micro-fluctuación institucional suave de **$\pm 0.01\%$ a $\pm 0.035\%$** (`noise = random.uniform(-0.00035, 0.00035)`) con reversión suave hacia `base_price` (que es el precio real descargado de Yahoo/Google) y un límite estricto de desviación máxima acumulada de `±0.08%` respecto a `base_price`:
       ```python
       base_p = float(q.get("base_price") or q.get("last_price", 1000.0))
       curr_p = float(q.get("last_price", base_p))
       mean_reversion = -0.25 * ((curr_p - base_p) / base_p) if base_p > 0 else 0.0
       noise = random.uniform(-0.00035, 0.00035)  # noqa: S311
       pct_step = noise + mean_reversion
       candidate = curr_p * (1.0 + pct_step)
       # Clamp within ±0.08% of real base_price so it never jumps wildly
       min_bound = base_p * 0.9992
       max_bound = base_p * 1.0008
       new_price = round(max(0.01, min(max_bound, max(min_bound, candidate))), 2)
       ```

2. **Gráfico `1D` Intradiario Real desde Yahoo Finance (`market_data_provider.py`, método `fetch_live_historical_bars`, líneas 1834-1913)**:
   - Reemplazar la generación sintética fija de `1D` por la consulta real a Yahoo Finance v8:
     - Consultar `cls.YAHOO_V8_URL.format(symbol=yahoo_sym, range_param="1d", interval_param="5m")` (y si devuelve `< 2` velas, consultar `range_param="5d", interval_param="5m"` y filtrar las velas cuya fecha en zona horaria `America/Argentina/Buenos_Aires` coincida con el último día operado).
     - De las velas intradiarias reales del día:
       - Extraer el precio de apertura real del día (`real_day_open = float(meta.get("regularMarketOpen") or raw_bars[0]["open"])`).
       - Actualizar `cls._LIVE_STATE[clean]["open_price"] = round(real_day_open, 2)` para que tabla y gráfico coincidan al 100%.
       - Asegurar que el **primer punto del gráfico `1D` (`bars[0]`)** tenga `open = real_day_open` y `close = raw_bars[0]["close"]` (ej. `$12.270` en `NVDA`), y que el **último punto (`bars[-1]`)** tenga `close = curr_price` (ej. `$12.180`).
       - Marcar cada vela entre `10:30` y `18:00 ART` con `"is_market_open": True`.
       - Si actualmente el mercado está cerrado (`not is_now_open`), agregar al final un tramo corto de continuación After-Hours (3 a 4 puntos desde las `18:00 ART` hasta `now_art` con `"is_market_open": False`) convergiendo suavemente a `curr_price`. Si el mercado está abierto (`is_now_open == True`), **no agregar puntos futuros posteriores a `now_art`**.

3. **Mostrar Marcador de Cierre / After-Hours ÚNICAMENTE en `1D` (`frontend/src/components/market/FinancialTimeSeriesChart.tsx` líneas 204-215, 250-260 y 365-417)**:
   - En `useMemo` (línea 206):
     ```tsx
     let transPt: { x: number; y: number; idx: number } | null = null;
     if (timeframe === "1D") {
       const transIdx = computedPoints.findIndex(
         (p, idx) => idx > 0 && computedPoints[idx - 1].bar.is_market_open && !p.bar.is_market_open
       );
       if (transIdx !== -1) {
         transPt = {
           x: computedPoints[transIdx].x,
           y: computedPoints[transIdx].y,
           idx: transIdx,
         };
       }
     }
     ```
   - En `market_data_provider.py` (línea 1969, para `1W`, `1M`, `1Y`), mantener `"is_market_open": True` en todas las barras diarias/semanales.
   - En `FinancialTimeSeriesChart.tsx` (línea 250), mostrar la leyenda de tramos de rueda (`Rueda Oficial BYMA` vs `After-Hours`) y la fila `Sesión:` del tooltip **únicamente cuando `timeframe === "1D"`**.

---

### PROBLEMA 4 (Video `00:58` - `01:05` y `02:56` - `03:18`): Horario Oficial de BYMA (`10:30 a 18:00 ART`) y Detección Automática del Horario de Mercado

#### Causa Raíz Detectada
- En el video son las `17:23 ART` y la plataforma muestra `MERCADO CERRADO (17:00 ART)`, cuando el mercado argentino opera de **`10:30 a 18:00 ART`** (sincronizado con el horario de mercado y operatoria vigente).
- El horario `11:00 a 17:00` estaba hardcodeado en `market_data_provider.py` (línea 1832), `marketService.ts` (líneas 292-293) y `FinancialTimeSeriesChart.tsx` (líneas 252 y 412).

#### Archivos y Líneas Exactas a Modificar

1. **Detección Automática + Horario Oficial `10:30 - 18:00 ART` en `backend/app/domain/services/market_data_provider.py`**:
   - Agregar en `PublicMarket10YProvider`:
     ```python
     _MARKET_OPEN_HM: tuple[int, int] = (10, 30)   # 10:30 ART
     _MARKET_CLOSE_HM: tuple[int, int] = (18, 0)   # 18:00 ART
     ```
   - Al recibir el JSON de Yahoo Finance v8 (`meta.currentTradingPeriod.regular`), inspeccionar los timestamps `start` y `end` en zona horaria `ART = timezone(timedelta(hours=-3))`:
     - Si Yahoo reporta una ventana válida en día hábil, combinarla de forma que cubra como mínimo la ventana operativa real de BYMA (`10:30` a `18:00 ART`).
   - Crear el método de clase `@classmethod def get_market_schedule_status(cls) -> dict[str, Any]`:
     ```python
     @classmethod
     def get_market_schedule_status(cls) -> dict[str, Any]:
         art_tz = timezone(timedelta(hours=-3))
         now_art = datetime.now(art_tz)
         is_weekday = now_art.weekday() < 5
         open_h, open_m = cls._MARKET_OPEN_HM
         close_h, close_m = cls._MARKET_CLOSE_HM
         now_mins = now_art.hour * 60 + now_art.minute
         open_mins = open_h * 60 + open_m
         close_mins = close_h * 60 + close_m
         is_open = is_weekday and (open_mins <= now_mins < close_mins)
         open_str = f"{open_h:02d}:{open_m:02d}"
         close_str = f"{close_h:02d}:{close_m:02d}"
         return {
             "is_market_open": is_open,
             "market_open_time": open_str,
             "market_close_time": close_str,
             "current_art_time": now_art.strftime("%H:%M:%S ART"),
         }
     ```
   - Incluir `is_market_open`, `market_open_time` (`"10:30"`) y `market_close_time` (`"18:00"`) en el diccionario devuelto por `fetch_live_quotes_batch()` (líneas 1799-1805) y en `/api/v1/market/live-quotes` (`backend/app/api/v1/endpoints/market.py` líneas 144-151).

2. **Actualizar `frontend/src/services/marketService.ts` (líneas 23-29 y 273-326)**:
   - Extender `LiveMarketFeedPayload`:
     ```tsx
     export interface LiveMarketFeedPayload {
       quotes: MarketQuote[];
       ccl_rate: number;
       mep_rate: number;
       data_source: string;
       updated_at: string;
       is_market_open?: boolean;
       market_open_time?: string;
       market_close_time?: string;
     }
     ```
   - En `getMarketStatus()` (líneas 291-325):
     - Cambiar `openMinutes = 10 * 60 + 30` (`10:30 ART`) y `closeMinutes = 18 * 60` (`18:00 ART`).
     - Actualizar los textos a `"Cierre de rueda hoy a las 18:00 ART"`, `"Apertura de rueda hoy a las 10:30 ART"`, `"Apertura próximo día hábil a las 10:30 ART"`, y `"Mercado fuera de horario. Rueda cerrada (10:30 a 18:00 ART)."`.

3. **Actualizar `MarketStatusBar.tsx` y `FinancialTimeSeriesChart.tsx`**:
   - Pasar `marketOpenTime={feedQuery.data?.market_open_time || "10:30"}` y `marketCloseTime={feedQuery.data?.market_close_time || "18:00"}` desde `MarketDataView.tsx`.
   - En `FinancialTimeSeriesChart.tsx`:
     - Leyenda: `Rueda Oficial BYMA (${marketOpenTime} - ${marketCloseTime} ART)`.
     - Pastilla divisoria en `1D`: `CIERRE ${marketCloseTime} → AFTER-HOURS (5s)`.

---

### PROBLEMA 5 (Video `03:26` - `04:08`): Altura y Textos Completos en los Botones del Selector Cuantitativo (`RebalancePanel.tsx`)

#### Causa Raíz Detectada
- En `frontend/src/components/portfolios/RebalancePanel.tsx` (líneas 428-459), los 5 botones de `QUANT_STRATEGIES` usan `truncate` en el título (`<span className="text-xs font-semibold truncate">{st.label}</span>`) y `line-clamp-1` en la fórmula, cortando los nombres a la mitad (`Automático (Pe...`, `Conservador (...`, `Moderado (Risk...`, `Agresivo (Max-...`).

#### Archivo y Líneas Exactas a Modificar (`frontend/src/components/portfolios/RebalancePanel.tsx`, líneas 416-461)

1. **Rediseñar las 5 tarjetas de `QUANT_STRATEGIES` (líneas 428-460)**:
   - Usar una grilla espaciosa `grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-5 gap-3`.
   - Dar a cada botón una altura mínima cómoda `min-h-[104px] p-3.5 rounded-xl border text-left transition-all flex flex-col justify-between gap-2`.
   - **Prohibido usar `truncate` o `line-clamp-1`**:
     - Renderizar el badge (`st.badge`) en la parte superior con un indicador de estado activo.
     - Renderizar el título completo (`st.label`) con `text-xs font-bold leading-snug whitespace-normal break-words text-white` para que se lea íntegro:
       - `Automático (Perfil)`
       - `Conservador (Min-Var 10Y)`
       - `Moderado (Risk Parity 10Y)`
       - `Agresivo (Max-Sharpe 10Y)`
       - `Equiponderado (1/N)`
     - Renderizar la descripción de la fórmula (`st.formula`) debajo con `text-[11px] font-mono leading-relaxed whitespace-normal break-words`.
2. **Mejorar el Banner de `FÓRMULA ACTIVA` (líneas 418-426)**:
   - Convertir el pequeño pill superior en un bloque destacado de ancho completo o tarjeta matemática clara con borde `border-sky-500/30 bg-slate-950/90 px-4 py-2.5 rounded-xl` que muestre claramente el nombre de la estrategia activa y su expresión matemática completa sin recortes.

---

### PROBLEMA 6 (Video `04:35` - `05:00`): Nuevo Logo Institucional de InvestAI Enterprise y Pulido de Botón Actualizar

#### Archivos a Crear / Modificar

1. **Crear `frontend/src/components/common/InvestAILogo.tsx`**:
   - Diseñar un componente SVG vectorial institucional (`size?: "sm" | "md" | "lg"`):
     - Escudo octogonal/hexagonal cuántico de finanzas cuantitativas con gradiente profundo (`#0284c7` -> `#10b981` -> `#6366f1`), barras ascendentes de precisión, curva de frontera eficiente de Markowitz con nodo brillante en la cúspide y anillo sutil de resplandor.
2. **Actualizar `frontend/src/components/layout/Sidebar.tsx` (líneas 85-102)**:
   - Reemplazar el cuadrado genérico de `<TrendingUp />` por `<InvestAILogo size="md" />` acompañado de la tipografía `InvestAI` + badge `ENTERPRISE PRO` con acabado metálico/cian y subtítulo `Quantitative Risk & BYMA Engine`.
3. **Actualizar `frontend/index.html` (línea 5)**:
   - Actualizar el `<link rel="icon" type="image/svg+xml" ...>` con el nuevo SVG vectorial de InvestAI Enterprise.
4. **Pulir `frontend/src/components/market/MarketStatusBar.tsx` (líneas 51-115)**:
   - Mostrar en una pastilla dedicada el horario oficial activo: `🕒 RUEDA BYMA: ${marketOpenTime} – ${marketCloseTime} ART`.
   - Rediseñar el botón **"Actualizar"** con estilo ejecutivo de alta gama (`bg-gradient-to-r from-sky-600 to-indigo-600 hover:from-sky-500 hover:to-indigo-500 border border-sky-400/30 shadow-lg shadow-sky-600/25`), feedback visual de sincronización (`Sincronizando MTM...` cuando `isRefreshing` es `true`) e indicador de auto-sync cada 5 segundos.

---

## PROTOCOLO DE VERIFICACIÓN FINAL (OBLIGATORIO ANTES DE CERRAR EL TURNO)

Una vez aplicadas las 6 remediaciones, ejecuta en orden:

1. **Verificación de Tests Backend (674 tests)**:
   ```powershell
   $env:PYTHONPATH="backend"; & "C:\Users\risso\AppData\Local\Python\bin\python.exe" -m pytest backend/tests -q
   ```
   *(Debe retornar `674 passed` con 0 fallos).*

2. **Verificación de Compilación y Tipado Frontend**:
   ```powershell
   npm --prefix frontend run build
   ```
   *(Debe completar `tsc && vite build` con 0 errores).*

3. **Verificación de Formato y Linter (`ruff` + `biome`)**:
   ```powershell
   npx --prefix frontend @biomejs/biome check --write frontend/src
   ```

4. **Registro en `docs/AUDIT_LEDGER.md`**:
   - Documentar el sellado del **APARTADO 15** con el resumen técnico de los 6 problemas resueltos.
