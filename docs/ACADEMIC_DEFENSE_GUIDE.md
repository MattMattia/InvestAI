# InvestAI Enterprise — Manual de Defensa Académica y Guía para el Tribunal Evaluador

> **Autor:** Mattia Risso  
> **Proyecto:** InvestAI Enterprise — Plataforma Institucional de Gestión de Portafolios, Ingeniería Financiera Cuantitativa, Control de Riesgo Determinista y Ejecución Asistida en BYMA  
> **Arquitectura:** Clean Architecture & Domain-Driven Design (FastAPI + SQLAlchemy 2.0 Async + React 18 + TypeScript + Tailwind CSS)  
> **Suite de Verificación:** **671 Pruebas Automatizadas Aprobadas (100% Passing)** | **0 Errores de Compilación TypeScript**

---

## 1. Resumen Ejecutivo para el Profesor Evaluador

**InvestAI Enterprise** es una plataforma integral de tecnología financiera (*WealthTech / Quant FinTech*) diseñada específicamente para la realidad bimonetaria del mercado de capitales argentino (**BYMA — Bolsas y Mercados Argentinos**, ** BCBA**, **MAE** y **NYSE/NASDAQ** vía CEDEARs).

A diferencia de soluciones genéricas que operan en una única moneda o que delegan decisiones críticas a modelos de caja negra no auditables, **InvestAI Enterprise** implementa un **núcleo cuantitativo 100% determinista, auditable y trazable**, donde cada valuación Mark-to-Market (MTM), cada alerta de riesgo normativo, cada cálculo de tipo de cambio implícito (**Dólar MEP / Dólar CCL**) y cada orden de rebalanceo está respaldada por ecuaciones matemáticas cerradas, álgebra lineal numéricamente estable y una Máquina de Estados Finitos (**FSM**) con liquidación contable real.

---

## 2. Puesta en Marcha en 1 Clic (Lanzador de Escritorio Windows)

El proyecto incluye una suite de automatización en PowerShell que inicializa la base de datos, siembra el catálogo calibrado de **26 especies líderes de BYMA**, levanta el backend asíncrono (FastAPI en puerto `8000`) y el frontend reactivo (Vite en puerto `5173`), verifica la salud de los subsistemas (`/health`) y abre la aplicación en modo ventana nativa de escritorio.

### 2.1. Inicio Rápido (1-Click)
1. **Desde el Escritorio de Windows:** Hacer doble clic en el acceso directo **`InvestAI Enterprise.lnk`**.
2. **Desde la carpeta raíz del proyecto:** Hacer doble clic en [`launch_investai.bat`](../scripts/launch_investai.bat) o ejecutar en PowerShell:
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\scripts\launch_investai.ps1
   ```
3. **Parada Limpia de Servicios:** Hacer doble clic en [`stop_investai.bat`](../scripts/stop_investai.bat) o ejecutar:
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\scripts\stop_investai.ps1
   ```

### 2.2. Credenciales Institucionales Pre-Sembradas
En la pantalla de inicio de sesión, el evaluador puede pulsar el botón **"Usar Demo"** (autocompletado en 1 clic) o ingresar manualmente:
- **Correo Electrónico:** `demo@investai.com`
- **Contraseña:** `InvestAI2026!`
- **Rol Inicial:** `TRADER` (con capacidad de conmutar en caliente entre `TRADER`, `ADMIN` y `VIEWER` desde el modal de perfil de usuario en la esquina superior derecha).

---

## 3. Recorrido Guiado de Demostración en Vivo (Guion de 10 Minutos)

Para una defensa fluida ante el tribunal, se sugiere seguir este orden cronológico de demostración sobre la interfaz:

### Paso 1: Autenticación Segura, Higiene Criptográfica y Conmutación RBAC (1 min)
1. Abrir la aplicación o cerrar sesión para mostrar el modal de acceso (`AuthModal`).
2. Destacar que los campos de credenciales se purgan estrictamente al abrir/cerrar el modal (`autoComplete="new-password"`), y que la pestaña **"Crear Cuenta"** incluye un **medidor visual en tiempo real de fortaleza de contraseña** (mínimo 8 caracteres, mayúscula y número/símbolo) y selector de Perfil de Inversor (`CONSERVATIVE`, `MODERATE`, `AGGRESSIVE`).
3. Iniciar sesión con el botón **"Usar Demo"** y hacer clic sobre el chip del usuario (`Usuario Demo InvestAI`) en la barra superior o lateral para abrir el **Modal de Perfil y Rol RBAC (`UserProfileModal`)**, demostrando cómo se puede alternar en caliente entre `TRADER`, `ADMIN` y `VIEWER` (`PATCH /api/v1/auth/me`) para verificar los bloqueos de seguridad en tiempo real.

### Paso 2: Dashboard de Portafolios, Gráfico Donut SVG y Tesorería Bimonetaria (2 min)
1. Ingresar a la **"Cartera Institucional Demo BYMA"** desde el panel principal.
2. En la pestaña **"Tenencias y Asignación"**, mostrar los **6 KPIs institucionales** en la cabecera (`Valuación ARS`, `Valuación USD`, `Caja ARS`, `Caja USD`, `Total Invertido`, `P&L no Realizado`).
3. Interactuar con el **Gráfico Donut SVG de Asignación por Activo**, alternando entre **`ARS`** y **`USD`** y pasando el cursor sobre cada segmento para observar la transición suave de grosor (`strokeWidth`) y opacidad sin recortes geométricos.
4. Hacer clic en el botón **"Depositar / Caja"** en la cabecera para abrir el **Modal de Tesorería Bimonetaria**, realizar un depósito instantáneo de `+$1.000.000 ARS` o `+US$ 5.000` y observar la actualización inmediata del patrimonio y del gráfico Donut. Mostrar también la pestaña **"Editar / Eliminar Cartera"**.

### Paso 3: Rebalanceo por Bandas de Tolerancia ($\tau$) y Liquidación FSM (2 min)
1. Cambiar a la pestaña **"Rebalanceo y Bandas FSM"** dentro del portafolio.
2. Seleccionar una banda de tolerancia $\tau$ (ej. `±2.0%` o `±5.0%`) y pulsar **"Simular Rebalanceo"**. Explicar que la simulación opera en modo idempotente (`?dry_run=true`), previsualizando las órdenes necesarias sin contaminar la base de datos con órdenes repetidas.
3. Pulsar **"Ejecutar Órdenes de Rebalanceo"** o dirigirse a la **Tabla de Registro Histórico de Órdenes FSM** más abajo, donde cada orden permite:
   - **"Ejecutar"**: Liquida la orden (`POST /api/v1/orders/{id}/execute`), deduce/acredita los aranceles reales de BYMA/CNV en la caja de la cartera y actualiza las tenencias (`HoldingModel`).
   - **"Cancelar"**: Transiciona la orden a `CANCELLED` (`POST /api/v1/orders/{id}/cancel`).
   - **"Detalle"**: Abre el comprobante forense con el desglose exacto de aranceles e impuestos.

### Paso 4: Auditoría Forense de Riesgo y Exportación de Certificado Normativo (1.5 min)
1. Cambiar a la pestaña **"Auditoría y Snapshots"**.
2. Hacer clic en **"Ejecutar Evaluación de Riesgo"** (`GET /api/v1/portfolios/{id}/evaluate`). El motor evalúa las 5 familias de reglas deterministas (Concentración por Activo, Concentración Sectorial, Piso de Renta Fija, Anomalías de Valuación Fundamental $P/E, PEG, EPS \le 0$, y Divergencia Cambiaria Implícita $CCL/MEP$) y persiste un snapshot inmutable.
3. Hacer clic en **"Inspeccionar Snapshot"** sobre cualquier fila del historial para abrir el **Dictamen Ejecutivo de Auditoría Forense (`SnapshotDetailModal`)**, mostrando las tarjetas semafóricas por regla, el botón **"Descargar (.json)"** y el acordeón técnico colapsable.

### Paso 5: Ingesta de Extractos Reales de Brokers Locales (Balanz Excel / CSV) (1.5 min)
1. Navegar desde la barra lateral a **"Ingesta de Extractos"** (`#ingestion`).
2. Explicar el pipeline de 3 etapas: **Detección Difusa de Esquema (`SchemaDetector`)** $\rightarrow$ **Limpieza y Normalización (`DataCleaningPipeline`)** $\rightarrow$ **Conciliación contra Cartera (`PortfolioReconciliationService`)**.
3. Demostrar cómo el motor reconoce encabezados reales de brokers argentinos como **Balanz** (`Descripcion, Cantidad, Precio, ValorActual, %Ganancia, Ganancia$, Moneda`) y limpia descripciones compuestas (`"CEDEAR NVDA"` $\rightarrow$ `"NVDA"`, `"GGAL - Grupo Financiero Galicia"` $\rightarrow$ `"GGAL"`, `"AL30 (Bono)"` $\rightarrow$ `"AL30"`).
4. Hacer clic en **"Precargar Extracto Demo Balanz"** (o subir un archivo `.xlsx`/`.csv` real de Balanz) y pulsar **"Procesar e Ingestar Extracto"** para visualizar la tarjeta de conciliación con las posiciones importadas.

### Paso 6: Monitor de Mercado BYMA en Tiempo Real, Selector ARS/USD CCL y Boleta Pre-Trade (1 min)
1. Navegar a **"Mercado en Vivo"** (`#market`).
2. Mostrar el catálogo de **26 especies líderes de BYMA** calibradas a precios reales de mercado (`GGAL` $\$5.120$, `YPFD` $\$30.200$, `COME` $\$32,00$, `NVDA` $\$14.290$, `AL30` $\$838,70$, `AL30D` $\text{US\$ } 68,45$, etc.).
3. Hacer clic en distintas especies de la tabla (`NVDA`, `COME`, `AL30D`, `YPFD`) y alternar entre horizontes (`1D`, `1S`, `1M`, `1A`) y el nuevo toggle **`ARS ($)` | `USD (CCL)`** en la esquina superior derecha del gráfico SVG (que convierte instantáneamente toda la serie histórica al Dólar CCL de referencia de $\$1.180\text{ ARS/USD}$ con **0ms de latencia**).
4. Pulsar **"Negociar"** sobre cualquier especie (o **"+ Nueva Orden"** en la cartera) para abrir la **Boleta de Ejecución Pre-Trade (`OrderExecutionModal`)**:
   - Mostrar el selector desplegable con las 26 especies BYMA, la detección automática de moneda nativa (`ARS` para acciones/CEDEARs/bonos en pesos vs `USD` para bonos `AL30D`/`GD30D`/`AE38D`), los botones rápidos de venta (`25%`, `50%`, `75%`, `100% Máx`) y el cálculo en vivo de **Arancel Broker ($0,50\%$)**, **IVA ($21\%$)** y **Derechos de Mercado BYMA/CNV ($0,10\%$)**.

### Paso 7: Observabilidad RED (`/metrics` Prometheus) y Salud del Sistema (1 min)
1. Navegar a **"Salud del Sistema"** (`#health`) y **"Métricas RED"** (`#metrics`).
2. Mostrar las **4 Tarjetas Ejecutivas de Telemetría** (`Volumen de Tráfico HTTP`, `Latencia Promedio RED`, `Disponibilidad / Errores 5xx`, y `Series Activas`), el buscador en vivo de series OpenMetrics y el conmutador para inspeccionar el payload crudo de Prometheus servido a través del proxy `/metrics`.

---

## 4. Arquitectura e Ingeniería de Software

### 4.1. Separación Estricta de Capas (Clean Architecture & DDD)
- **Capa de Dominio Puro (`backend/app/domain/`):** Libre de dependencias de FastAPI o SQLAlchemy. Contiene las entidades financieras, reglas de riesgo (`BaseRiskRule`), optimizadores matriciales (`portfolio_optimizer.py`), estabilidad numérica (`numerical_stability.py`), regímenes de Markov (`markov_regime.py`), fricciones de mercado (`market_frictions.py`), detectores de esquema (`schema_detector.py`) y motor de backtesting (`backtest_engine.py`).
- **Capa de Aplicación y Servicios (`backend/app/services/`):** Coordina casos de uso transaccionales, valuación MTM bimonetaria, conciliación de extractos y aislamiento multitenant.
- **Capa de Infraestructura y Persistencia (`backend/app/models/`, `backend/app/core/`):** Modelos relacionales asíncronos en SQLAlchemy 2.0, migraciones Alembic, seguridad criptográfica (`security.py`) y observabilidad Prometheus (`metrics.py`).
- **Capa de Presentación Reactiva (`frontend/src/`):** SPA en React 18 + TypeScript estricto + Vite + TanStack Query v5, con gráficos financieros y de asignación construidos en **SVG vectorial puro** (0 dependencias pesadas de gráficos externos, garantizando rendimiento instantáneo y control geométrico total).

---

## 5. Preguntas Frecuentes del Tribunal Evaluador (Q&A de Defensa)

### P1: *¿Por qué se eligió un motor de riesgo determinista y optimización convexa con contracción de Ledoit-Wolf en lugar de un modelo puramente basado en IA generativa?*
- **Respuesta:** En la gestión patrimonial institucional y el cumplimiento normativo (CNV / Basilea), cada alerta de riesgo y cada orden de rebalanceo debe ser **100% reproducible, explicable y auditable**. Además, en mercados emergentes como BYMA donde las series históricas pueden ser cortas ($T < N$) o presentar alta colinealidad cambiaria, la matriz de covarianza muestral clásica se vuelve singular o mal condicionada. Mediante la **contracción analítica de Ledoit-Wolf (2004)** combinada con la **proyección espectral de Higham (2002)** (`safe_cholesky`), garantizamos matemáticamente que la matriz de covarianza sea siempre simétrica y estrictamente definida positiva, permitiendo resolver tanto **Global Minimum Variance (GMV)** como **Risk Parity (ERC de Spinu, 2013)** sin fallos de convergencia.

### P2: *¿Cómo resuelve el sistema la problemática bimonetaria argentina (ARS vs USD, MEP y CCL) y la asimetría de feriados entre BYMA y Wall Street?*
- **Respuesta:** El dominio modela explícitamente las monedas `ARS`, `USD`, `USD_MEP` y `USD_CCL`. Para activos duales y CEDEARs, el sistema calcula el tipo de cambio implícito aplicando los ratios oficiales de conversión de BCBA:
  $$\text{CCL}_{\text{implícito}} = \frac{\text{Precio CEDEAR (ARS)} \times \text{Ratio CEDEAR}}{\text{Precio Subyacente NYSE/NASDAQ (USD)}}$$
  Asimismo, el servicio `calendar_service.py` sincroniza los calendarios bursátiles de **BYMA** y **NYSE** (2024–2027) aplicando *Forward-Fill* determinista con etiquetado de estado `STALE_MARKET_CLOSED` cuando una plaza opera y la otra permanece cerrada por feriado local.

### P3: *¿Qué mecanismos de ciberseguridad protegen los portafolios y las órdenes de negociación?*
- **Respuesta:** Se implementó una arquitectura de defensa en profundidad (**SEC-03**):
  1. **Autenticación y Sesiones:** Hash de contraseñas con **Bcrypt/Argon2**, tokens JWT `HS256` con identificador único `jti`, rotación de *Refresh Tokens* y revocación en lista negra (`TokenBlacklist`).
  2. **Autorización RBAC:** Control de acceso basado en roles (`ADMIN`, `TRADER`, `VIEWER`) verificado en base de datos en cada request mediante la dependencia `RoleChecker`.
  3. **Mitigación Anti-IDOR / Anti-BOLA (OWASP API1:2023):** Ningún endpoint confía únicamente en el UUID del recurso; todas las consultas y mutaciones de portafolios, tenencias, snapshots y órdenes filtran por `PortfolioModel.user_id == current_user.id` (devolviendo `404 Not Found` ante intentos de acceso cruzado para no filtrar la existencia del recurso).
  4. **Protección Anti-SSRF e Ingesta Segura:** Los conectores externos validan dominios contra listas blancas y bloquean rangos IP privados/loopback, mientras que el parser de archivos valida tamaño máximo (15 MB), extensión y estructura antes de procesar.

---

## 6. Comandos de Verificación Rápida para el Tribunal

Para ejecutar la suite completa de **671 pruebas automatizadas** y verificar la compilación limpia del frontend en menos de 10 segundos:

```powershell
# 1. Ejecutar las 671 pruebas unitarias y de integración del Backend (modo silencioso)
$env:PYTHONPATH="backend"; python -m pytest backend/tests -q

# 2. Verificar tipado estricto TypeScript y empaquetado de producción del Frontend
npm --prefix frontend run build
```

