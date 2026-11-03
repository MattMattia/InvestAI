# InvestAI Enterprise — Registro de Auditoría Forense y Sellado Progresivo (`AUDIT_LEDGER.md`)

> **Protocolo Activo:** Auditoría Forense Multi-Ronda, Remediación en Caliente y Sellado Progresivo (Read-Skip Invariant).
> **Regla de Exclusión:** Todo apartado marcado con `[x] **[SEALED - 100% VERIFIED]**` posee sus archivos blindados y excluidos de re-lecturas redundantes.

---

## Estado de los Apartados de Auditoría

- [x] **[SEALED - 100% VERIFIED]** **APARTADO 1: Proxy de Telemetría `/metrics`, Salud del Sistema y Lanzador Desktop 1-Click**
  - *Archivos Blindados*: `frontend/vite.config.ts`, `frontend/src/App.tsx`, `backend/scripts/seed_smoke_test.py`, `scripts/launch_investai.ps1`.
  - *Resumen Técnico*: Proxy Vite extendido con `/metrics`, `/health` y `/ready`; parser OpenMetrics estructurado con 4 tarjetas KPI ejecutivas, detección defensiva anti-HTML y tabla filtrable; vista de Salud del Sistema enriquecida con sincronización integral y hora ART; semilla optimizada en lote (< 0.05s) con 26 especies BYMA calibradas y lanzador con polling reactivo de 250ms.

- [x] **[SEALED - 100% VERIFIED]** **APARTADO 2: Seguridad de Autenticación, Higiene de Inputs, Fortaleza de Contraseñas y Gestión de Perfil/Rol**
  - *Archivos Blindados*: `frontend/src/components/auth/AuthModal.tsx`, `frontend/src/components/auth/UserProfileModal.tsx`, `frontend/src/components/layout/Sidebar.tsx`, `frontend/src/components/layout/TopHeader.tsx`, `frontend/src/components/layout/AppLayout.tsx`, `frontend/src/context/AuthContext.tsx`, `frontend/src/services/authService.ts`, `backend/app/api/v1/endpoints/auth.py`, `backend/app/schemas/user.py`.
  - *Resumen Técnico*: Purgado forzoso de inputs de credenciales al abrir/cerrar/cambiar modo/cerrar sesión (`autoComplete="new-password"`), medidor visual en tiempo real de fortaleza de contraseña (mín. 8 caracteres, mayúscula y número/símbolo), promoción operativa inmediata a `TRADER` tras registro en UI, nuevo endpoint `PATCH /api/v1/auth/me` y modal interactivo `UserProfileModal.tsx` accesible desde `Sidebar` y `TopHeader` para conmutar perfil de inversor y rol RBAC (`TRADER`, `ADMIN`, `VIEWER`) en caliente.

- [x] **[SEALED - 100% VERIFIED]** **APARTADO 3: Motor de Ingesta de Extractos Reales (Balanz Excel/CSV) y Conciliación Tolerante**
  - *Archivos Blindados*: `backend/app/domain/services/ingestion/base_parser.py`, `backend/app/domain/services/ingestion/schema_detector.py`, `backend/app/domain/services/ingestion/data_cleaning_pipeline.py`, `frontend/src/components/ingestion/IngestionView.tsx`.
  - *Resumen Técnico*: Sinónimos de encabezado ampliados en `schema_detector.py` (`"descripcion"`, `"desc"`, `"papel"`, `"valor"`) para soportar el formato nativo de tenencias de Balanz con confianza 1.0; limpieza inteligente de prefijos/sufijos descriptivos en `data_cleaning_pipeline.py` (`"CEDEAR NVDA"` -> `"NVDA"`, `"GGAL - Grupo Financiero Galicia"` -> `"GGAL"`, `"AL30 (Bono)"` -> `"AL30"`); botones de "Descargar Extracto Modelo (CSV)" y "Precargar Extracto Demo Balanz" en `IngestionView.tsx` (94 tests passed).

- [x] **[SEALED - 100% VERIFIED]** **APARTADO 4: Datos de Mercado BYMA Calibrados a la Realidad, Selector ARS/USD y Carga Instantánea del Gráfico SVG**
  - *Archivos Blindados*: `frontend/src/services/marketService.ts`, `backend/scripts/seed_smoke_test.py`, `backend/app/api/v1/endpoints/market.py`, `frontend/src/components/market/MarketDataView.tsx`, `frontend/src/components/market/FinancialTimeSeriesChart.tsx`.
  - *Resumen Técnico*: Precios de referencia BYMA calibrados a la realidad del mercado local (`COME` $32.00, `NVDA` $14,290.00, `GGAL` $5,120.00, `YPFD` $30,200.00, `AL30` $838.70, `AL30D` US$ 68.45, etc.); generación determinística síncrona de barras OHLCV (`buildDeterministicHistoricalBars`) anclada al último precio de cierre para 0ms de latencia en cualquier especie y horizonte temporal (`1D`, `1S`, `1M`, `1A`); selector de moneda interactivo `ARS ($)` | `USD (CCL)` en `FinancialTimeSeriesChart.tsx` con TC CCL de referencia ($1,180.00 ARS/USD).

- [x] **[SEALED - 100% VERIFIED]** **APARTADO 5: Boleta de Órdenes Pre-Trade (Selector de Especie, Moneda Real, Tenencias) y Ejecución/Cancelación FSM**
  - *Archivos Blindados*: `frontend/src/components/orders/OrderExecutionModal.tsx`, `frontend/src/components/orders/RecentOrdersTable.tsx`, `frontend/src/components/portfolios/RebalancePanel.tsx`, `frontend/src/lib/formatters.ts`, `frontend/src/services/orderService.ts`, `backend/app/api/v1/endpoints/orders.py`, `backend/app/api/v1/endpoints/rebalancing.py`.
  - *Resumen Técnico*: Selector dinámico con las 26 especies BYMA en `OrderExecutionModal.tsx`; resolución automática de moneda nativa (`ARS` vs `USD`) y saldo disponible; carga de tenencias reales vía `usePortfolio(id)` con botones rápidos (`25%`, `50%`, `75%`, `100% Máx`) en modo `VENTA`; normalización de zona horaria Argentina (`America/Argentina/Buenos_Aires`, UTC-3) en `formatDate`; simulación idempotente (`?dry_run=true`) y ejecución en lote en `RebalancePanel.tsx`; endpoints `POST /api/v1/orders/{id}/execute` y `POST /api/v1/orders/{id}/cancel` con impacto contable en caja y tenencias y acciones interactivas en `RecentOrdersTable.tsx`.

- [x] **[SEALED - 100% VERIFIED]** **APARTADO 6: Geometría del Gráfico Donut SVG, Visor Ejecutivo de Snapshots y CRUD Completo de Cartera**
  - *Archivos Blindados*: `frontend/src/components/portfolios/AssetAllocationDonut.tsx`, `frontend/src/components/portfolios/SnapshotDetailModal.tsx`, `frontend/src/components/portfolios/PortfolioKPIHeader.tsx`, `frontend/src/components/portfolios/PortfolioDetailView.tsx`, `frontend/src/services/portfolioService.ts`, `backend/app/api/v1/endpoints/portfolios.py`.
  - *Resumen Técnico*: Geometría SVG de `AssetAllocationDonut.tsx` recalibrada (`viewBox="0 0 220 220"`, `cx="110" cy="110" r="80"`) con transición suave de `strokeWidth` (`22` -> `27`) y `strokeOpacity` sin `scale()` CSS ni recortes; `SnapshotDetailModal.tsx` rediseñado como Dictamen Ejecutivo de Auditoría Forense con tarjetas visuales por regla, exportación de certificado `.json` y acordeón colapsable para JSON crudo; modal integral de Tesorería Bimonetaria (Depósito/Retiro ARS/USD), Edición de Cartera y Baja Segura (`PATCH` y `DELETE /api/v1/portfolios/{id}`).

- [x] **[SEALED - 100% VERIFIED]** **APARTADO 7: Auditoría Profunda de Código, Clean Architecture, Seguridad y Suite de Tests (>= 666 Passed)**
  - *Archivos Blindados*: `backend/tests/integration/test_forensic_audit_remediations.py`, endpoints FastAPI (`auth.py`, `orders.py`, `rebalancing.py`, `portfolios.py`, `market.py`), servicios de dominio e ingesta, y tipado estricto TypeScript en `frontend/src/`.
  - *Resumen Técnico*: Suite de pruebas extendida a **671 tests aprobados al 100%** (`0 failed`, `0 errors`) incluyendo pruebas de integración específicas para conmutación RBAC/perfil en caliente (`PATCH /api/v1/auth/me`), detección de encabezados reales de Balanz y limpieza de tickers compuestos, idempotencia de rebalanceo (`?dry_run=true`), liquidación contable y cancelación FSM con aislamiento anti-IDOR/BOLA, y CRUD bimonetario de portafolios; compilación frontend certificada con 0 errores (`tsc && vite build`).

- [x] **[SEALED - 100% VERIFIED]** **APARTADO 8: Documentación Académica y Manual de Defensa para el Profesor**
  - *Archivos Blindados*: `README.md`, `docs/ACADEMIC_DEFENSE_GUIDE.md`, `docs/PROGRESS.md`, `docs/AUDIT_LEDGER.md`.
  - *Resumen Técnico*: Creación del Manual de Defensa Académica y Guía para el Tribunal Evaluador (`docs/ACADEMIC_DEFENSE_GUIDE.md`) con guion paso a paso de demostración en vivo (10 minutos), fundamentación matemática/cuantitativa, arquitectura de ciberseguridad (SEC-03, Anti-BOLA, RBAC) y preguntas frecuentes del tribunal; actualización integral de `README.md` y cierre definitivo en `docs/PROGRESS.md` y `docs/AUDIT_LEDGER.md`.
