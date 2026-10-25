# Bitácora Viva de Avance: InvestAI Enterprise (PROGRESS.md)

> **Estado Global del Proyecto:**  
> **Progreso Consolidado:** 22 de 26 Módulos Completados (84.6%) — Capítulos 1 a 6 completados al 100%; Capítulo 7 en progreso (Módulo 7.1 completado al 100%, Módulo 7.2 Fases 1 y 2 completadas)  
> **Capítulos Implementados:** Capítulos 1, 2, 3, 4, 5 y 6 (100% completados)  
> **Capítulos Pendientes / En Progreso:** Capítulo 7 (en progreso), Capítulos 8 y 9  
> **Calidad y Suite de Pruebas:** **389 tests pasando al 100% en verde (311 unitarios + 78 de integración)**  
> **Última Actualización:** 2026-10-21

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
| **Capítulo 7** | Motores Cuantitativos Avanzados, Señales y Valuación MTM | 1 / 3 | 5 / 9 | **EN PROGRESO** | 389 tests (+30) |
| **Capítulo 8** | Ciclo de Vida de Base de Datos (Alembic) y Background Tasks | 0 / 3 | 0 / 8 | **PENDIENTE** | - |
| **Capítulo 9** | Frontend Dashboard Reactivo (React 18 + Vite + TypeScript) | 0 / 3 | 0 / 9 | **PENDIENTE** | - |

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
  - [x] Fase 3: Pruebas Unitarias de Precisión Numérica contra Benchmarks (`backend/tests/unit/test_technical_indicators.py`, `backend/app/domain/services/__init__.py` — endurecimiento de precisión intermedia `localcontext(prec=50)`, re-exportación limpia y 6 pruebas analíticas de benchmark y estrés; 17 pruebas totales cerrando el Módulo 7.1 al 100%)
- [ ] **Módulo 7.2: Valuación Patrimonial Dinámica y PnL Multimoneda (TWR / MWR)**
  - [x] Fase 1: Motor de Valuación Mark-to-Market Bimoneda (`backend/app/domain/services/portfolio_valuation_service.py`, `backend/tests/unit/test_portfolio_valuation.py` — valuación bimoneda ARS/USD, descomposición multiplicativa Karnosky-Singer, Largest Remainder weights, TWR GIPS, Modified Dietz e IRR exacto con 7 pruebas unitarias)
  - [x] Fase 2: Métricas de Rendimiento Ponderado, Curva de Valuación Histórica y Drawdown Bimonetario (`backend/app/domain/services/portfolio_valuation_service.py`, `backend/tests/unit/test_portfolio_valuation.py` — descomposición Karnosky-Singer a nivel cartera, aperturas en `$0` con timing `START`, `HistoricalValuationSnapshot`, `ValuationCurvePoint`, `PortfolioValuationCurveReport`, High-Water Mark / Drawdown bimonetario e integración `value_holdings_from_quotes` con 6 pruebas unitarias nuevas; 13 total en el módulo)
  - [ ] Fase 3: Pruebas Unitarias y de Integración con Saltos Cambiarios
- [ ] **Módulo 7.3: Rebalanceo por Bandas de Tolerancia Dinámicas (Tolerance-Band Rebalance)**
  - [ ] Fase 1: Algoritmo de Bandas de Tolerancia Dinámicas (`tolerance_band_rebalancer.py`)
  - [ ] Fase 2: Determinación de Órdenes Óptimas de Rebalanceo con Costos ALyC
  - [ ] Fase 3: Pruebas de Simulación de Deriva de Cartera (Portfolio Drift)

---

### CAPÍTULO 8: Ciclo de Vida de Base de Datos y Automatización en Background
- [ ] **Módulo 8.1: Versionado y Migraciones Estructuradas con Alembic**
  - [ ] Fase 1: Inicialización y Parametrización Asíncrona de Alembic (`env.py`, `alembic.ini`)
  - [ ] Fase 2: Generación de Migraciones Base para todas las Entidades
  - [ ] Fase 3: Pruebas de Migración hacia adelante (`upgrade`) y hacia atrás (`downgrade`)
- [ ] **Módulo 8.2: Schedulers de Ingesta Bursátil Programada y Bloqueo Concurrente**
  - [ ] Fase 1: Orquestador de Tareas Programadas al Cierre de Rueda (`market_scheduler.py`)
  - [ ] Fase 2: Bloqueos Distribuidos y Concurrencia (Redis / Locks relacionales)
- [ ] **Módulo 8.3: Monitoreo Institucional y Métricas RED (Prometheus / Grafana)**
  - [ ] Fase 1: Instrumentación del Endpoint `/metrics` con métricas RED (Rate, Errors, Duration)
  - [ ] Fase 2: Exportación de Métricas Cuantitativas (latencias de solvers, fallbacks, cache hits)

---

### CAPÍTULO 9: Frontend Dashboard Reactivo (React + Vite + TypeScript)
- [ ] **Módulo 9.1: Arquitectura Base, Design System y Contratos DTO Tipados**
  - [ ] Fase 1: Inicialización del Proyecto (`frontend/`, React 18+, Vite, TypeScript estricto, Tailwind CSS)
  - [ ] Fase 2: Sincronización y Espejado de Contratos DTO Tipados
  - [ ] Fase 3: Shell de la Aplicación, Layout Institucional y Gestión de Sesión
- [ ] **Módulo 9.2: Visualización Financiera Avanzada (TradingView Lightweight Charts)**
  - [ ] Fase 1: Componente Reutilizable de Velas Japonesas y Líneas (`CandleChart`)
  - [ ] Fase 2: Visualizador en Tiempo Real de Arbitraje Cambiario (MEP / CCL)
  - [ ] Fase 3: Gráficos de Evolución de Patrimonio, Áreas de Drawdown y Benchmarks
- [ ] **Módulo 9.3: Centro de Carga de Extractos, Monitoreo de Riesgo y Gestión de Carteras**
  - [ ] Fase 1: Dropzone Interactivo de Carga de Extractos (CSV/Excel)
  - [ ] Fase 2: Matriz Semafórica de Cumplimiento de Reglas de Riesgo
  - [ ] Fase 3: Panel de Órdenes y Rebalanceo Asistido con Cómputo Previo de Comisiones

---

## Siguiente Paso Inmediato

> **Foco Actual:** **CAPÍTULO 7 — Módulo 7.2 (Fase 3): Pruebas Unitarias y de Integración con Saltos Cambiarios y Flujos Intermedios (`backend/tests/unit/test_portfolio_valuation.py`)**  
> **Prioridad:** Alta (Cierre del Módulo 7.2 tras completar la Fase 2 con 389 tests en verde)  
> **Objetivo:** Implementar la suite exhaustiva de pruebas de estrés con saltos cambiarios extremos (devaluaciones discretas del peso argentino), flujos de caja intermedios multipaso, reconciliación de valuación post-ingesta y cierre completo del Módulo 7.2.

### Hoja de Ruta Inmediata para el Capítulo 7:
1. **Módulo 7.2 (Fase 3)**: Implementar la suite exhaustiva de pruebas unitarias y de integración con saltos cambiarios y depósitos intermedios (`backend/tests/unit/test_portfolio_valuation.py`).
2. **Módulo 7.3 (Fase 1)**: Implementar el algoritmo de rebalanceo por bandas de tolerancia dinámicas (`backend/app/domain/services/tolerance_band_rebalancer.py`).
3. **Módulo 7.3 (Fase 2)**: Implementar la determinación de órdenes óptimas de rebalanceo con costos ALyC.





