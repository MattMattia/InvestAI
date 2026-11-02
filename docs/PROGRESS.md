# Bitácora Viva de Avance: InvestAI Enterprise (PROGRESS.md)

> **Estado Global del Proyecto:**  
> **Progreso Consolidado:** 26 de 26 Módulos del Backend Completados (100.0%) — Capítulos 1 al 8 completados en su totalidad  
> **Capítulos Implementados:** Capítulos 1, 2, 3, 4, 5, 6, 7 y 8 (100% completados)  
> **Capítulos Pendientes / En Progreso:** Capítulo 9 (Frontend Dashboard Reactivo) — Módulo 9.1 en progreso  
> **Calidad y Suite de Pruebas:** **666 tests pasando al 100% en verde (582 unitarios + 84 de integración)**  
> **Última Actualización:** 2026-11-02

---

## Protocolo Obligatorio de Actualización
> [!IMPORTANT]
> **Regla de Trabajo para el Agente:** Al finalizar cada Fase o Módulo en sesiones presentes o futuras, es **requisito obligatorio** actualizar este archivo (`docs/PROGRESS.md`), reflejando el nuevo estado de los checkboxes (`- [x]`), el recuento total acumulado de pruebas unitarias y de integración, y la sección de *Siguiente Paso Inmediato*.

---

## Resumen Ejecutivo por Capítulo

| Capítulo | Título | Módulos | Fases Totales | Estado | Cobertura / Tests |
| :--- | :--- | :---: | :---: | :---: | :--- |
| **Capítulo 1** | Fundaciones del Dominio Cuantitativo y Arquitectura Base | 5 / 5 | 10 / 10 | **COMPLETADO** | 137 tests |
| **Capítulo 2** | Auditoría Integral y Diagnóstico Técnico (`AUDIT_REPORT.md`) | 2 / 2 | 6 / 6 | **COMPLETADO** | Informe formal emitido |
| **Capítulo 3** | Remediación Técnica y Hardening Post-Auditoría | 5 / 5 | 17 / 17 | **COMPLETADO** | 159 tests (+22) |
| **Capítulo 4** | Conectividad Externa, Ingesta en Vivo y Datos de Mercado | 4 / 4 | 14 / 14 | **COMPLETADO** | 205 tests (+46) |
| **Capítulo 5** | Seguridad Criptográfica, Autenticación y RBAC (SEC-03) | 4 / 4 | 9 / 9 | **COMPLETADO** | 293 tests (+88) |
| **Capítulo 6** | Ingesta de Reportes Locales y Pipeline de Calidad de Datos | 3 / 3 | 9 / 9 | **COMPLETADO** | 359 tests (+66) |
| **Capítulo 7** | Motores Cuantitativos Avanzados, Señales y Valuación MTM | 3 / 3 | 9 / 9 | **COMPLETADO** | 621 tests (+262) |
| **Capítulo 8** | Ciclo de Vida de Base de Datos y Automatización en Background | 3 / 3 | 7 / 7 | **COMPLETADO** | 666 tests (+45) |
| **Capítulo 9** | Frontend Dashboard Reactivo (React 18 + Vite + TypeScript) | 2 / 3 | 7 / 9 | **EN PROGRESO** | Build Frontend Verificado |

---

## Checklist Detallado de Implementación

### CAPÍTULO 1: Fundaciones del Dominio Cuantitativo y Arquitectura Base
- [x] **Módulo 1.1: Álgebra Lineal Cuantitativa y Regularización Espectral**
  - [x] Fase 1: Contracción Óptima de Covarianza (Ledoit-Wolf) (`quantitative_risk.py`)
  - [x] Fase 2: Factorización de Cholesky Segura y Proyección Espectral de Higham (`numerical_stability.py`)
- [x] **Módulo 1.2: Motores de Optimización de Carteras (SLSQP y Risk Parity)**
  - [x] Fase 1: Portafolio de Varianza Mínima Global (GMV / SLSQP) (`portfolio_optimizer.py`)
  - [x] Fase 2: Paridad de Riesgo / Equal Risk Contribution (ERC / Spinu L-BFGS-B) (`portfolio_optimizer.py`)
- [x] **Módulo 1.3: Máquina de Estados Finitos (FSM) y Microestructura de Fricciones**
  - [x] Fase 1: FSM Transaccional de Órdenes (`order.py`)
  - [x] Fase 2: Motor de Fricciones y Liquidación Local (BYMA / ALyC / IVA) (`market_frictions.py`)
- [x] **Módulo 1.4: Motor de Backtesting y Simulación Estocástica**
  - [x] Fase 1: Simulador de Portafolios Paso a Paso y Métricas Cuantitativas (`backtest_engine.py`)
  - [x] Fase 2: Generador Estocástico Browniano Geométrico (GBM correlacionado)
- [x] **Módulo 1.5: Persistencia Relacional y Capa de Exposición Inicial**
  - [x] Fase 1: Modelado Relacional SQLAlchemy (`PortfolioModel`, `HoldingModel`, `OrderModel`)
  - [x] Fase 2: Endpoints HTTP Base y Suite de Testing Original (137 tests en verde)

---

### CAPÍTULO 2: Auditoría Integral y Diagnóstico Técnico (`AUDIT_REPORT.md`)
- [x] **Módulo 2.1: Diagnóstico de Arquitectura, Contratos y Seguridad en Transporte**
  - [x] Fase 1: Identificación de Fugas de Dominio (Transport Leaks en routers)
  - [x] Fase 2: Evaluación de Contratos de Entrada y Transporte (falta de Universal Envelope y `extra="forbid"`)
  - [x] Fase 3: Detección de Brechas Perimetrales (SEC-01 CORS, SEC-02 500 Leak, SEC-03 Mock User)
- [x] **Módulo 2.2: Diagnóstico Numérico Cuantitativo y Evaluación de Pruebas**
  - [x] Fase 1: Diagnóstico de Singularidades Matemáticas (NUM-01 Spinu con varianza cero, NUM-02 no-finitud)
  - [x] Fase 2: Diagnóstico de Fricciones y Manejo de Series (NUM-03 contracción temporal, NUM-04 caja negativa)
  - [x] Fase 3: Diagnóstico de Infraestructura de Pruebas y Observabilidad (TST-01, OBS-01, OBS-02)

---

### CAPÍTULO 3: Remediación Técnica y Hardening Post-Auditoría
- [x] **Módulo 3.1: Seguridad Defensiva y Sanitización Inmediata (SEC-01, SEC-02, ARQ-01)**
  - [x] Fase 1: Endurecimiento Perimetral CORS y Sanitización de Respuestas (`main.py`)
  - [x] Fase 2: Esquemas Hardened con `ConfigDict(extra="forbid", str_strip_whitespace=True)`
  - [x] Fase 3: Verificación y Testing de Frontera (140 tests en verde)
- [x] **Módulo 3.2: Estabilización Numérica y Mitigación Adversarial (NUM-01 a NUM-04)**
  - [x] Fase 1: Aislamiento de Activos Planos en Spinu ERC (NUM-01)
  - [x] Fase 2: Validación de No-Finitud y Fallbacks Seguros en Solvers (NUM-02)
  - [x] Fase 3: Unión Temporal con Imputación Segura en Backtesting (NUM-03)
  - [x] Fase 4: Piso No Negativo en Liquidación de Ventas Residuales (NUM-04)
  - [x] Fase 5: Verificación y Testing Adversarial (146 tests en verde)
- [x] **Módulo 3.3: Modernización de la Suite de Pruebas (TST-01)**
  - [x] Fase 1: Parametrización Formal de Pytest (`backend/pytest.ini`)
  - [x] Fase 2: Arnés Global de Fixtures (`backend/tests/conftest.py`)
  - [x] Fase 3: Saneamiento de Fugas de Conexiones SQLite y Deprecaciones RFC 9110
- [x] **Módulo 3.4: Desacoplamiento Arquitectónico y Universal Envelope (ARQ-02, ARQ-03)**
  - [x] Fase 1: Extracción del Servicio Estocástico GBM al Dominio (`market_simulation.py`)
  - [x] Fase 2: Implementación de Contratos Canónicos Universal Envelope (`envelope.py`)
  - [x] Fase 3: Estandarización de Manejadores de Excepciones HTTP 422 y 500
  - [x] Fase 4: Verificación y Testing de Envelopes (154 tests en verde)
- [x] **Módulo 3.5: Observabilidad y Telemetría de Producción (OBS-01, OBS-02)**
  - [x] Fase 1: Middleware ASGI de Correlación `X-Request-ID` y Latencia (`trace.py`)
  - [x] Fase 2: Sondas Semánticas de Salud (`/health/liveness` y `/health/readiness`)
  - [x] Fase 3: Verificación y Testing de Observabilidad (159 tests en verde)

---

### CAPÍTULO 4: Conectividad Externa, Ingesta en Vivo y Datos de Mercado
- [x] **Módulo 4.1: Contratos Canónicos y Calculadora FX (MEP/CCL)**
  - [x] Fase 1: Contratos DTO Inmutables (`market_data.py`: `MarketQuoteDTO`, `MarketBarDTO`, `FXRateDTO`)
  - [x] Fase 2: Calculadora Cuantitativa Pura (`fx_calculator.py`: `calculate_mep_rate`, `calculate_ccl_rate`)
  - [x] Fase 3: Hardening y Auditoría de Microestructura Bursátil (VWAP acotado, UTC estricto, `ROUND_HALF_UP`)
  - [x] Fase 4: Suite de Verificación de Contratos y Arbitraje (171 tests en verde)
- [x] **Módulo 4.2: Conectores Asíncronos, Resiliencia y Blindaje SSRF**
  - [x] Fase 1: Contrato de Proveedor Abstracto (`BaseMarketConnector` en `market_connector.py`)
  - [x] Fase 2: Guardián de Seguridad Perimetral Anti-SSRF (`ssrf_guard.py` con bloqueo IP privadas/cloud)
  - [x] Fase 3: Cliente HTTP Asíncrono Resiliente (`HttpMarketConnector` con retry, backoff y timeouts)
  - [x] Fase 4: Suite de Verificación de Red Hermética (185 tests en verde)
- [x] **Módulo 4.3: Persistencia Relacional, Deduplicación Delta y Caché Volátil**
  - [x] Fase 1: Modelo Relacional de Series Temporales (`MarketBarModel` en `market_data.py`)
  - [x] Fase 2: Caché en Memoria con Reloj Monótono (`InMemoryQuoteCache` con TTL en `quote_cache.py`)
  - [x] Fase 3: Servicio de Historial e Ingesta Delta (`MarketHistoryService` con deduplicación)
  - [x] Fase 4: Suite de Verificación de Persistencia y Caché (190 tests en verde)
- [x] **Módulo 4.4: Controladores REST (Universal Envelope) e Integración con Backtesting**
  - [x] Fase 1: Inyección de Dependencias y Rutas (`deps.py`, `market.py`, `/api/v1/market/*`)
  - [x] Fase 2: Adaptador Cuantitativo para Backtesting (`bars_to_price_history` en `backtest_engine.py`)
  - [x] Fase 3: Suite de Verificación de Endpoints e Integración (205 tests en verde)

---

### CAPÍTULO 5: Seguridad Criptográfica, Autenticación y Control de Acceso (SEC-03)
- [x] **Módulo 5.1: Modelo de Identidad, Hashing Criptográfico y Gestión de Secretos**
  - [x] Fase 1: Contratos Canónicos de Identidad y Modelo Relacional de Usuario (`backend/app/schemas/user.py`, `backend/app/infrastructure/db/models/user.py`, `backend/tests/unit/test_user_contracts.py`, `backend/tests/integration/test_user_persistence.py`)
  - [x] Fase 2: Servicio de Hashing Defensivo (Bcrypt nativo con `SecretStr` en `core/security.py`, `backend/tests/unit/test_security_crypto.py`)
- [x] **Módulo 5.2: Motor de Tokens Criptográficos (JWT / OAuth2 Bearer)**
  - [x] Fase 1: Contratos de Token, Configuración Criptográfica y Motor de Access Tokens JWT (`backend/app/schemas/token.py`, `backend/app/core/security.py`, `backend/tests/unit/test_security_jwt.py`)
  - [x] Fase 2: Flujo de Refresco de Tokens (Refresh Tokens con ciclo de renovación y token pair) (`backend/app/schemas/token.py`, `backend/app/core/security.py`, `backend/tests/unit/test_security_jwt.py`)
- [x] **Módulo 5.3: Dependencias de Seguridad, RBAC y Aislamiento Anti-IDOR (SEC-03)**
  - [x] Fase 1: Dependencias de Seguridad, Inyección OAuth2 Bearer y Control de Acceso RBAC (`backend/app/api/deps.py`, `backend/app/api/__init__.py`, `backend/tests/unit/test_security_deps.py`)
  - [x] Fase 2: Erradicación del Mock X-User-Id, Control de Propiedad Tenant y Aislamiento Anti-IDOR/BOLA (`backend/app/api/deps.py`, `backend/app/services/portfolio_service.py`, `backend/app/api/v1/endpoints/*`, `backend/tests/integration/test_api_endpoints.py`, `backend/tests/integration/test_api_backtest.py`)
  - [x] Fase 3: Aislamiento Multitenant Estricto (Filtro mandatorio de `user_id` en endpoints de cartera, órdenes y backtest)
- [x] **Módulo 5.4: Controlador REST de Autenticación, Endpoints /auth y Rate Limiting Defensivo**
  - [x] Fase 1: Controlador REST de Autenticación, Endpoints `/auth` (`/register`, `/login`, `/refresh`, `/me` bajo Universal Envelope) y Suite de Integración (`backend/app/schemas/auth.py`, `backend/app/api/v1/endpoints/auth.py`, `backend/tests/integration/test_api_auth.py`)
  - [x] Fase 2: Rate Limiting Defensivo y Mitigación de Fuerza Bruta en `/auth` (`backend/app/core/rate_limit.py`, `backend/app/api/deps.py`, `backend/tests/unit/test_rate_limiter.py`, `backend/tests/integration/test_api_auth.py`)
  - [x] Auditoría Adversarial E2E (Red-Team / Blue-Team) y Hardening del Capítulo 5 (`AUD-C5-01` a `AUD-C5-05` — 293 tests en verde: 225 unitarios + 68 de integración)

---

### CAPÍTULO 6: Ingesta de Reportes Locales y Pipeline de Calidad de Datos
- [x] **Módulo 6.1: Parser Desacoplado de Extractos y Reportes de ALyCs (CSV / Excel)**
  - [x] Fase 1: Interfaz Abstracta de Parsing y Estrategias por Formato (`backend/app/domain/services/ingestion/base_parser.py`, `backend/app/domain/services/ingestion/excel_parser.py`, `backend/app/domain/services/ingestion/csv_parser.py`, `backend/tests/unit/test_report_parsers.py`)
  - [x] Fase 2: Detección Automática de Esquemas y Normalización de Columnas (Fuzzy Matching en `backend/app/domain/services/ingestion/schema_detector.py`, `backend/tests/unit/test_report_parsers.py`)
  - [x] Fase 3: Suite de Pruebas con Muestras Sintéticas de Brokers Locales (`backend/tests/unit/test_report_parsers.py` — 25 pruebas unitarias de ingesta cubriendo Balanz, IOL, PPI, Bull Market, Caja de Valores y vectores adversariales ZIP/CSV)
- [x] **Módulo 6.2: Pipeline de Validación, Normalización y Tratamiento Contable (EPS $\le$ 0)**
  - [x] Fase 1: Pipeline de Saneamiento y Limpieza Monetaria (`backend/app/domain/services/ingestion/data_cleaning_pipeline.py`, `backend/tests/unit/test_data_cleaning_pipeline.py` — 10 pruebas unitarias)
  - [x] Fase 2: Manejo de Inconsistencias de Balance (etiquetado `INDETERMINATE` para ratios patológicos en `backend/app/domain/services/accounting_integrity.py`, `backend/tests/unit/test_accounting_integrity.py`)
  - [x] Fase 3: Suite de Pruebas de Calidad Contable y Balances Extremos (`backend/tests/unit/test_accounting_integrity.py` — 12 pruebas unitarias de estrés contable e integración E2E con `DataCleaningPipeline`)
- [x] **Módulo 6.3: Integración Transaccional y Conciliación Automática de Tenencias**
  - [x] Fase 1: Servicio de Conciliación de Cartera (`backend/app/domain/services/portfolio_reconciliation.py`, `backend/tests/unit/test_portfolio_reconciliation.py` — 9 pruebas unitarias transaccionales y de contratos)
  - [x] Fase 2: Controlador REST de Ingesta (`POST /api/v1/ingestion/upload-report` en `backend/app/api/v1/endpoints/ingestion.py` y `IngestionReportSummary` en `backend/app/schemas/ingestion.py`)
  - [x] Fase 3: Pruebas de Integración E2E con Carga Multiparte (`backend/tests/integration/test_api_ingestion.py` — 10 pruebas de integración E2E multiparte cerrando el Capítulo 6 al 100%)
  - [x] Auditoría Adversarial E2E (Red-Team / Blue-Team) y Hardening Integral del Capítulo 6 (`MAX_ZIP_ENTRIES`, cuantización sub-pip `HOLDING_DECIMAL_QUANTIZE`, blindaje `imports.py` / `ingestion.py` — 359 tests en verde: 281 unitarios + 78 de integración)

---

### CAPÍTULO 7: Motores Cuantitativos Avanzados, Señales y Valuación Mark-to-Market
- [x] **Módulo 7.1: Indicadores Técnicos y Generador de Señales Cuantitativas**
  - [x] Fase 1: Biblioteca de Indicadores Numéricos Vectorizados (`backend/app/domain/services/technical_indicators.py`, `backend/tests/unit/test_technical_indicators.py` — SMA, EMA, RSI Wilder, Bollinger, ATR y `TechnicalIndicatorsSnapshot` con 6 pruebas unitarias)
  - [x] Fase 2: Motor de Generación de Señales de Negociación (`backend/app/domain/services/signal_generator.py`, `backend/tests/unit/test_technical_indicators.py` — reglas deterministas EMA/SMA/RSI/Bollinger, dimensionamiento ATR y `OrderFSMIntent` con 5 pruebas unitarias nuevas; 11 total en el módulo)
  - [x] Fase 3: Pruebas Unitarias de Precisión Numérica contra Benchmarks (`backend/tests/unit/test_technical_indicators.py`, `backend/app/domain/services/__init__.py` — endurecimiento de precisión intermedia `localcontext(prec=50)`, re-exportación limpia y 65 pruebas unitarias totales en el módulo tras expansión de auditoría)
- [x] **Módulo 7.2: Valuación Patrimonial Dinámica y PnL Multimoneda (TWR / MWR)**
  - [x] Fase 1: Motor de Valuación Mark-to-Market Bimoneda (`backend/app/domain/services/portfolio_valuation_service.py`, `backend/tests/unit/test_portfolio_valuation.py` — valuación bimoneda ARS/USD, descomposición multiplicativa Karnosky-Singer, Largest Remainder weights, TWR GIPS, Modified Dietz e IRR exacto con 7 pruebas unitarias)
  - [x] Fase 2: Métricas de Rendimiento Ponderado, Curva de Valuación Histórica y Drawdown Bimonetario (`backend/app/domain/services/portfolio_valuation_service.py`, `backend/tests/unit/test_portfolio_valuation.py` — descomposición Karnosky-Singer a nivel cartera, aperturas en `$0` con timing `START`, `HistoricalValuationSnapshot`, `ValuationCurvePoint`, `PortfolioValuationCurveReport`, High-Water Mark / Drawdown bimonetario e integración `value_holdings_from_quotes` con 6 pruebas unitarias nuevas; 13 total en el módulo)
  - [x] Fase 3: Pruebas Unitarias y de Integración con Saltos Cambiarios (`backend/tests/unit/test_portfolio_valuation.py`, `backend/app/domain/services/portfolio_valuation_service.py` — endurecimiento de casos de borde de rondas 1 a 5, certificación GIPS, shock hiperinflacionario 300%, solver IRR no lineal con Dietz < -1.0, curva diaria de 365 días, frontera $10^{12}$ y 71 pruebas unitarias totales en el módulo tras expansión de auditoría)
- [x] **Módulo 7.3: Rebalanceo por Bandas de Tolerancia Dinámicas (Tolerance-Band Rebalance)**
  - [x] Fase 1: Algoritmo de Bandas de Tolerancia Dinámicas (`backend/app/domain/services/tolerance_band_rebalancer.py`, `backend/tests/unit/test_tolerance_band_rebalancer.py` — bandas absolutas, relativas y escaladas por volatilidad dinámica, modos `FULL_TO_TARGET` y `TO_BAND_BOUNDARY`, cascada autofinanciada `SELL`-before-`BUY` con comisiones y buffer de liquidez, integración con `PortfolioMarkToMarketReport` y `OrderFSMIntent`, y 7 pruebas unitarias)
  - [x] Fase 2: Calibración Dinámica vía ATR, Proyección Post-Trade con Estimación de PnL Realizado, Despliegue de Exceso de Liquidez y Lote de Ejecución Idempotente hacia la FSM (`backend/app/domain/services/tolerance_band_rebalancer.py`, `backend/tests/unit/test_tolerance_band_rebalancer.py` — `calibrate_specs_from_indicators`, `deploy_excess_cash_when_inside_bands`, `estimated_realized_pnl`, `RebalanceFSMOrderTicket`, `RebalanceFSMExecutionBatch`, `build_fsm_execution_batch` y 6 pruebas unitarias nuevas; 13 total en el módulo)
  - [x] Fase 3: Selección Fiscal de Lotes (`FIFO`/`LIFO`/`HIFO`), Endurecimiento de las 10 Rondas de Auditoría y Suite Exhaustiva de Certificación Cuantitativa E2E (`backend/app/domain/services/tolerance_band_rebalancer.py`, `backend/app/domain/services/__init__.py`, `backend/tests/unit/test_tolerance_band_rebalancer.py` — `TaxLotSelectionPolicy`, Largest Remainder exacto en `post_trade_weight`, redistribución asimétrica en `TO_BAND_BOUNDARY`, conversión bimonetaria unitaria, preservación de `avg_cost_price=None` y 71 pruebas unitarias totales en el módulo tras expansión de auditoría)
  - [x] Auditoría Forense de 6 Rondas, Hardening Defensivo, Verificación de Servidor Uvicorn en Vivo y Expansión Exacta de Pruebas del Capítulo 7 (`backend/tests/unit/test_chapter7_adversarial_audit.py` con 55 pruebas adversariales E2E + expansión de `test_technical_indicators.py` a 65, `test_portfolio_valuation.py` a 71 y `test_tolerance_band_rebalancer.py` a 71 — **621 tests totales en verde: 543 unitarios + 78 de integración**)

---

### CAPÍTULO 8: Ciclo de Vida de Base de Datos y Automatización en Background
- [x] **Módulo 8.1: Versionado y Migraciones Estructuradas con Alembic**
  - [x] Fase 1: Inicialización y Parametrización Asíncrona de Alembic (`alembic.ini`, `backend/alembic/env.py`, `backend/alembic/script.py.mako`, `backend/tests/unit/test_alembic_setup.py` — convención declarativa `POSTGRES_NAMING_CONVENTION` en `Base.metadata`, exportación canónica de modelos en `backend/app/models/__init__.py`, resolución segura de URLs asíncronas con escape `%%`, `render_as_batch=is_sqlite` y 7 pruebas unitarias nuevas; **628 tests totales en verde: 550 unitarios + 78 de integración**)
  - [x] Fase 2: Sincronización Exacta, Normalización Tipada Multi-Dialecto y Certificación Reversible de la Migración Base (`backend/alembic/versions/001_initial_schema.py`, `backend/tests/unit/test_alembic_migrations.py` — sincronía estructural 1:1 de las 7 tablas de `Base.metadata.tables` con ordenamiento topológico estricto en `upgrade` e inverso con `drop_index` previo en `downgrade`, portabilidad PostgreSQL/SQLite con variantes tipadas `JSONB`/`JSON` y `Numeric`, idempotencia de ciclo completo `upgrade head` -> `downgrade base` -> `upgrade head`, y 6 pruebas unitarias nuevas; **634 tests totales en verde: 556 unitarios + 78 de integración**)
  - [x] Fase 3: Pruebas de Migración hacia adelante (`upgrade`) y hacia atrás (`downgrade`) (`backend/tests/integration/test_alembic_lifecycle.py` — verificación de ciclo de vida DDL completo, aislamiento estricto Windows file-lock safety, integridad referencial con `PRAGMA foreign_keys=ON` (`CASCADE` de usuario a portfolio/holding y `RESTRICT` de activo en uso), unicidad compuesta en `market_bars`, índices únicos en `users`, roundtrip estructurado JSON/Numeric, rollback transaccional ante fallos en vuelo y 6 pruebas de integración nuevas; **640 tests totales en verde: 556 unitarios + 84 de integración**)
- [x] **Módulo 8.2: Schedulers de Ingesta Bursátil Programada y Bloqueo Concurrente**
  - [x] Fase 1: Orquestador de Tareas Programadas al Cierre de Rueda (`market_scheduler.py`, `backend/tests/unit/test_market_scheduler.py` — calendario BYMA con detección de feriados recurrentes y variables, contratos DTO inmutables `PortfolioCloseInput`, `MarketCloseJobConfig`, `PortfolioCloseProcessResult`, `MarketCloseJobReport`, agregación de órdenes FSM con `ToleranceBandRebalancerService`, aislamiento de fallas por cartera e invariantes contables con 7 pruebas unitarias nuevas; **647 tests totales en verde: 563 unitarios + 84 de integración**)
  - [x] Fase 2: Bloqueos Distribuidos y Concurrencia (Redis / Locks relacionales) (`market_scheduler.py`, `backend/app/domain/services/__init__.py`, `backend/tests/unit/test_market_scheduler_locks.py` — contratos DTO `LockAcquireResult`, protocolos abstractos `DistributedLockProtocol` y `SnapshotPersistenceProtocol`, implementaciones `InMemoryLockManager` con TTL monotónico y token safety, `RedisLockManager` con script atómico Lua para release seguro, ejecución asíncrona segura con bypass `force_rerun`, persistencia inmutable de auditoría y 6 pruebas unitarias nuevas; **653 tests totales en verde: 569 unitarios + 84 de integración**)
- [x] **Módulo 8.3: Monitoreo Institucional y Métricas RED (Prometheus / Grafana)**
  - [x] Fase 1: Instrumentación del Endpoint `/metrics` con métricas RED (Rate, Errors, Duration) (`backend/app/core/metrics.py`, `backend/app/main.py`, `backend/tests/unit/test_metrics_instrumentation.py` — recolector centralizado `InvestAIMetrics`, contadores RED `http_requests_total`, `http_request_duration_seconds` e `http_requests_exceptions_total`, telemetría de scheduler, defensa contra cardinalidad con `normalize_route_path`, middleware asíncrono `MetricsMiddleware`, endpoint `/metrics` con token opcional `METRICS_SCRAPE_TOKEN` y 7 pruebas unitarias nuevas; **660 tests totales en verde: 576 unitarios + 84 de integración**)
  - [x] Fase 2: Exportación de Métricas Cuantitativas (latencias de solvers, fallbacks, cache hits) (`backend/app/core/metrics.py`, `backend/app/core/__init__.py`, `backend/tests/unit/test_quant_metrics.py` — telemetría especializada de solvers `quant_solver_duration_seconds` y `quant_solver_iterations`, contadores de fallbacks y conmutaciones algorítmicas `quant_solver_fallbacks_total` con sanitización de cardinalidad, métricas de aciertos y desaciertos de caché de cotizaciones `market_data_cache_hits_total` y `market_data_cache_misses_total`, wrappers a nivel de módulo y 6 pruebas unitarias nuevas; **666 tests totales en verde: 582 unitarios + 84 de integración**)

---

### CAPÍTULO 9: Frontend Dashboard Reactivo (React + Vite + TypeScript)
- [x] **Módulo 9.1: Arquitectura Base, Design System y Contratos DTO Tipados**
  - [x] Fase 1: Inicialización del Proyecto (`frontend/`, React 18+, Vite, TypeScript estricto, Tailwind CSS) (`frontend/package.json`, `frontend/tsconfig.json`, `frontend/vite.config.ts`, `frontend/tailwind.config.js`, `frontend/src/index.css`, `frontend/index.html`, `frontend/src/lib/authStorage.ts`, `frontend/src/lib/apiClient.ts`, `frontend/src/types/api.ts`, `frontend/src/App.tsx`, `frontend/src/main.tsx` — Scaffolding React 18/Vite con TypeScript estricto y Tailwind CSS institucional financiero, cliente Axios tipado con propagación de `X-Request-ID` UUIDv4, mutex asíncrono anti-estampida para renovación automática de tokens JWT ante 401, abstracción tipada `ApiError` para errores 422 de Pydantic, contratos DTO 1:1 espejo con FastAPI, shell de verificación contra `/health` y `/metrics`, y build certificado con 0 errores de compilación; **666 tests de backend intactos**)
  - [x] Fase 2: Gestión de Sesión Reactiva, Proveedor de Autenticación (`AuthContext` / `useAuth`), Servicios de API y Sincronización Multi-Pestaña (`frontend/src/types/api.ts`, `frontend/src/services/authService.ts`, `frontend/src/context/AuthContext.tsx`, `frontend/src/hooks/useAuth.ts`, `frontend/src/components/auth/AuthModal.tsx`, `frontend/src/main.tsx`, `frontend/src/App.tsx` — Tipado desacoplado de credenciales y registros, servicio `authService` integrado con `/api/v1/auth/login`, `/register`, `/me` y `/refresh`, contexto `AuthContext` con sincronización multi-pestaña `window.storage`, invalidación y cancelación inmediata de queries con TanStack `QueryClient`, hook `useAuth()` con validación de scope, modal accesible `AuthModal` con Escape/backdrop, mapeo granular de errores 422 de Pydantic y conmutación reactiva de usuario y rol `ADMIN`/`TRADER`/`VIEWER` en header; build verificado con 0 errores de compilación y **666 tests de backend intactos**)
  - [x] Fase 3: Layout Institucional Financiero, Navegación URL-First con RBAC, Fábrica de Query Keys y Dashboard de Portafolios (`frontend/src/lib/queryKeys.ts`, `frontend/src/lib/formatters.ts`, `frontend/src/services/portfolioService.ts`, `frontend/src/hooks/usePortfolios.ts`, `frontend/src/components/layout/Sidebar.tsx`, `frontend/src/components/layout/TopHeader.tsx`, `frontend/src/components/layout/AppLayout.tsx`, `frontend/src/components/portfolios/PortfolioCard.tsx`, `frontend/src/components/portfolios/CreatePortfolioModal.tsx`, `frontend/src/components/portfolios/PortfoliosView.tsx`, `frontend/src/App.tsx` — Fábrica centralizada de claves TanStack Query v5 `portfolioKeys`/`systemKeys`, utilidades de parseo defensivo decimal `parseDecimalSafe` y formateo monetario bimoneda ARS/USD `formatMoney`, servicio `portfolioService` integrado con `/portfolios`, hooks reactivos `usePortfolios` y `useCreatePortfolio` con invalidación de caché, layout modular `AppLayout` con navegación URL-first sincronizada por hashchange, `Sidebar` institucional con telemetría de sesión, `TopHeader` con breadcrumbs y semáforo `/health`, dashboard de portafolios `PortfoliosView` con métricas agregadas de patrimonio y caja, control de acceso RBAC para creación de carteras `TRADER`/`ADMIN` y modal accesible `CreatePortfolioModal`; build verificado con 0 errores y **666 tests de backend intactos**)
- [x] **Módulo 9.2: Visualización Financiera Avanzada y Detalle de Activos**
  - [x] Fase 1: Vista de Detalle de Portafolio, Composición de Tenencias, P&L no Realizado y Gráfico Donut de Asignación por Activos (`frontend/src/lib/navigation.ts`, `frontend/src/lib/formatters.ts`, `frontend/src/types/api.ts`, `frontend/src/components/portfolios/AssetAllocationDonut.tsx`, `frontend/src/components/portfolios/HoldingsTable.tsx`, `frontend/src/components/portfolios/PortfolioKPIHeader.tsx`, `frontend/src/components/portfolios/PortfolioDetailView.tsx`, `frontend/src/components/portfolios/PortfolioCard.tsx`, `frontend/src/components/portfolios/PortfoliosView.tsx`, `frontend/src/components/layout/AppLayout.tsx`, `frontend/src/components/layout/TopHeader.tsx`, `frontend/src/App.tsx` — Enrutador hash URL-first `#portfolios?id=<uuid>` con hook reactivo `useHashRoute`, tipado enriquecido `HoldingWithMetrics` con cálculo defensivo anti-división por cero, formateador institucional `formatSignedPercent` y `formatMoney` bimoneda, gráfico Donut SVG puro y accesible con selector ARS/USD, integración de caja y hover sincronizado, tabla de tenencias `HoldingsTable` con valuación MTM, chips de P&L y barras de ponderación, cabecera de analítica `PortfolioKPIHeader` con KPIs agregados, y vista de detalle `PortfolioDetailView`; build certificado con 0 errores y **666 tests de backend intactos**)
  - [x] Fase 2: Panel de Rebalanceo Dinámico, Detección de Brechas de Bandas y Simulación de Órdenes FSM (`frontend/src/lib/navigation.ts`, `frontend/src/types/api.ts`, `frontend/src/services/portfolioService.ts`, `frontend/src/components/portfolios/ToleranceBandVisualizer.tsx`, `frontend/src/components/portfolios/FSMOrdersPreviewTable.tsx`, `frontend/src/components/portfolios/RebalancePanel.tsx`, `frontend/src/components/portfolios/PortfolioDetailView.tsx` — Enrutamiento hash extendido con pestañas `#portfolios?id=<uuid>&tab=<tab>`, contratos DTO enriquecidos `RebalanceOrder`, `ToleranceBandItem` y `RebalanceSimulationResult`, método `simulateRebalance` conectado al motor Tolerance-Band de FastAPI `/portfolios/{id}/rebalance`, visualizador de bandas horizontales con detección semafórica de excesos y déficits, tabla institucional de órdenes FSM con justificaciones cuantitativas y mensajes de equilibrio, panel de control de rebalanceo con selectores de divisa y $\tau$ (2%, 5%, 10%), buffer de liquidez, guardianes de posiciones y control de acceso RBAC; build verificado con 0 errores y **666 tests de backend intactos**)
  - [x] Fase 3: Auditoría de Cumplimiento, Historial de Snapshots, Inspección Forense de Riesgo y Cierre del Módulo 9.2 (`backend/app/api/v1/endpoints/risk.py`, `frontend/src/lib/navigation.ts`, `frontend/src/lib/queryKeys.ts`, `frontend/src/lib/formatters.ts`, `frontend/src/types/api.ts`, `frontend/src/services/portfolioService.ts`, `frontend/src/components/portfolios/SnapshotDetailModal.tsx`, `frontend/src/components/portfolios/SnapshotHistoryTable.tsx`, `frontend/src/components/portfolios/AuditCompliancePanel.tsx`, `frontend/src/components/portfolios/PortfolioDetailView.tsx` — Endpoint GET `/api/v1/portfolios/{id}/snapshots` con aislamiento multitenant, extensión de contratos DTO `RiskAuditSnapshot`, normalización defensiva de payload JSON `normalizeSnapshotPayload`, claves de consulta reactivas `snapshotKeys`, panel de cumplimiento normativo `AuditCompliancePanel` con resumen ejecutivo, disparador interactivo de snapshots con RBAC `TRADER`/`ADMIN`, tabla cronológica de auditoría `SnapshotHistoryTable` con badges semafóricos de estado (`COMPLIANCE_OK` / `BREACH_DETECTED`) y conteo de alertas críticas, modal accesible `SnapshotDetailModal` con visor JSON inspeccionable y botón de copiado con confirmación visual, y pestaña dedicada en `PortfolioDetailView` sincronizada vía hash `#portfolios?id=<uuid>&tab=audit`; build verificado con 0 errores y **666 tests de backend intactos**)
- [ ] **Módulo 9.3: Centro de Carga de Extractos, Monitoreo de Riesgo y Gestión de Carteras**
  - [x] Fase 1: Dropzone Interactivo de Carga de Extractos (CSV/Excel), Ingesta Multipart y Previsualización de Datos Normalizados (`frontend/src/lib/navigation.ts`, `frontend/src/types/api.ts`, `frontend/src/services/ingestionService.ts`, `frontend/src/components/ingestion/ExtractDropzone.tsx`, `frontend/src/components/ingestion/UploadProgressBar.tsx`, `frontend/src/components/ingestion/IngestionSummaryCard.tsx`, `frontend/src/components/ingestion/IngestionView.tsx`, `frontend/src/components/layout/Sidebar.tsx`, `frontend/src/components/layout/TopHeader.tsx`, `frontend/src/App.tsx` — Enrutamiento `#ingestion`, contratos `BrokerReportUploadResponse`, servicio multipart con streaming de progreso `uploadBrokerReport` hacia `/api/v1/ingestion/upload-report`, dropzone interactivo con validación dual (.csv, .xlsx, .xls y 15 MB) y blindaje anti-parpadeo, barra fluida con cancelación por `AbortController`, tarjeta de reporte con badge de broker (Balanz, IOL, PPI, etc.) y desglose de conciliación, selector de cartera con `usePortfolios`, guardia de seguridad RBAC para `TRADER`/`ADMIN` con candado en `VIEWER`, e invalidación paralela de cachés en TanStack Query v5; build verificado con 0 errores y **666 tests de backend intactos**)
  - [ ] Fase 2: Monitor de Cotizaciones BYMA en Tiempo Real y Gráficos Financieros
  - [ ] Fase 3: Panel de Órdenes y Rebalanceo Asistido con Cómputo Previo de Comisiones

---

## Siguiente Paso Inmediato

> **Foco Actual:** **CAPÍTULO 9 — Módulo 9.3 (Fase 2): Monitor de Cotizaciones BYMA en Tiempo Real y Gráficos Financieros**  
> **Prioridad:** Alta (Continuación del Módulo 9.3 tras certificar la ingesta de extractos de brokers locales en Fase 1)  
> **Objetivo:** Implementar la visualización de cotizaciones de mercado en tiempo real, streaming o polling de precios BYMA, variaciones diarias, selector de especies y gráficos financieros interactivos (velas OHLCV / líneas de tendencia).

### Hoja de Ruta Inmediata para el Capítulo 9:
1. **Módulo 9.1**: Arquitectura Base, Autenticación Reactiva y Dashboard de Portafolios — COMPLETADO [x] (3 / 3 fases).
2. **Módulo 9.2**: Visualización Financiera Avanzada y Detalle de Activos — COMPLETADO [x] (3 / 3 fases).
3. **Módulo 9.3 (Fase 1)**: Dropzone Interactivo de Carga de Extractos (CSV/Excel) e Ingesta de Reportes — COMPLETADO [x].
4. **Módulo 9.3 (Fase 2)**: Monitor de Cotizaciones BYMA en Tiempo Real y Gráficos Financieros.
5. **Módulo 9.3 (Fase 3)**: Panel de Órdenes y Rebalanceo Asistido con Cómputo Previo de Comisiones.







