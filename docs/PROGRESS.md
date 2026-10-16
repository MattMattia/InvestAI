# Bitácora Viva de Avance: InvestAI Enterprise (PROGRESS.md)

> **Estado Global del Proyecto:**  
> **Progreso Consolidado:** 17 de 26 Módulos Completados (65.4%) — Módulos 5.1, 5.2, 5.3 y 5.4 (Fase 1) completados  
> **Capítulos Implementados:** Capítulos 1, 2, 3 y 4 (100% completados)  
> **Capítulos Pendientes / En Progreso:** Capítulos 5 (En Curso), 6, 7, 8 y 9  
> **Calidad y Suite de Pruebas:** **279 tests pasando al 100% en verde (216 unitarios + 63 de integración)**  
> **Última Actualización:** 2026-10-16

---

## Protocolo Obligatorio de Actualización
> [!IMPORTANT]
> **Regla de Trabajo para el Agente:** Al finalizar cada Fase o Módulo en sesiones presentes o futuras, es **requisito obligatorio** actualizar este archivo (`docs/PROGRESS.md`), reflejando el nuevo estado de los checkboxes (`- [x]`), el recuento total acumulado de pruebas unitarias y de integración, y la sección de *Siguiente Paso Inmediato*.

---

## Resumen Ejecutivo por Capítulo

| Capítulo | Título | Módulos | Fases Totales | Estado | Cobertura / Tests |
| :--- | :--- | :---: | :---: | :---: | :---: |
| **Capítulo 1** | Fundaciones del Dominio Cuantitativo y Arquitectura Base | 5 / 5 | 10 / 10 | **COMPLETADO** | 137 tests |
| **Capítulo 2** | Auditoría Integral y Diagnóstico Técnico (`AUDIT_REPORT.md`) | 2 / 2 | 6 / 6 | **COMPLETADO** | Informe formal emitido |
| **Capítulo 3** | Remediación Técnica y Hardening Post-Auditoría | 5 / 5 | 17 / 17 | **COMPLETADO** | 159 tests (+22) |
| **Capítulo 4** | Conectividad Externa, Ingesta en Vivo y Datos de Mercado | 4 / 4 | 14 / 14 | **COMPLETADO** | 205 tests (+46) |
| **Capítulo 5** | Seguridad Criptográfica, Autenticación y RBAC (SEC-03) | 3 / 4 (M5.1, M5.2, M5.3 y M5.4 F1 completados) | 8 / 9 | **EN PROGRESO** | 279 tests (+74) |
| **Capítulo 6** | Ingesta de Reportes Locales y Pipeline de Calidad de Datos | 0 / 3 | 0 / 9 | **PENDIENTE** | - |
| **Capítulo 7** | Motores Cuantitativos Avanzados, Señales y Valuación MTM | 0 / 3 | 0 / 9 | **PENDIENTE** | - |
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
- [ ] **Módulo 5.4: Controlador REST de Autenticación, Endpoints /auth y Rate Limiting Defensivo**
  - [x] Fase 1: Controlador REST de Autenticación, Endpoints `/auth` (`/register`, `/login`, `/refresh`, `/me` bajo Universal Envelope) y Suite de Integración (`backend/app/schemas/auth.py`, `backend/app/api/v1/endpoints/auth.py`, `backend/tests/integration/test_api_auth.py`)
  - [ ] Fase 2: Rate Limiting Defensivo y Mitigación de Fuerza Bruta en `/auth`

---

### CAPÍTULO 6: Ingesta de Reportes Locales y Pipeline de Calidad de Datos
- [ ] **Módulo 6.1: Parser Desacoplado de Extractos y Reportes de ALyCs (CSV / Excel)**
  - [ ] Fase 1: Interfaz Abstracta de Parsing y Estrategias por Formato (`base_parser.py`, `excel_parser.py`, `csv_parser.py`)
  - [ ] Fase 2: Detección Automática de Esquemas y Normalización de Columnas (Fuzzy Matching en `schema_detector.py`)
  - [ ] Fase 3: Suite de Pruebas con Muestras Sintéticas de Brokers Locales
- [ ] **Módulo 6.2: Pipeline de Validación, Normalización y Tratamiento Contable (EPS $\le$ 0)**
  - [ ] Fase 1: Pipeline de Saneamiento y Limpieza Monetaria (`data_cleaning_pipeline.py`)
  - [ ] Fase 2: Manejo de Inconsistencias de Balance (etiquetado `INDETERMINATE` para ratios patológicos)
  - [ ] Fase 3: Suite de Pruebas de Calidad Contable y Balances Extremos
- [ ] **Módulo 6.3: Integración Transaccional y Conciliación Automática de Tenencias**
  - [ ] Fase 1: Servicio de Conciliación de Cartera (`PortfolioReconciliationService`)
  - [ ] Fase 2: Controlador REST de Ingesta (`POST /api/v1/ingestion/upload-report`)
  - [ ] Fase 3: Pruebas de Integración E2E con Carga Multiparte

---

### CAPÍTULO 7: Motores Cuantitativos Avanzados, Señales y Valuación Mark-to-Market
- [ ] **Módulo 7.1: Indicadores Técnicos y Generador de Señales Cuantitativas**
  - [ ] Fase 1: Biblioteca de Indicadores Numéricos Vectorizados (SMA, EMA, RSI Wilder, Bollinger, ATR)
  - [ ] Fase 2: Motor de Generación de Señales de Negociación (`signal_generator.py`)
  - [ ] Fase 3: Pruebas Unitarias de Precisión Numérica contra Benchmarks
- [ ] **Módulo 7.2: Valuación Patrimonial Dinámica y PnL Multimoneda (TWR / MWR)**
  - [ ] Fase 1: Motor de Valuación Mark-to-Market Bimoneda (`portfolio_valuation_service.py`)
  - [ ] Fase 2: Métricas de Rendimiento Ponderado (Time-Weighted Return y Money-Weighted Return)
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

> **Foco Actual:** **CAPÍTULO 5 - MÓDULO 5.4: Controlador REST de Autenticación, Endpoints /auth y Rate Limiting Defensivo - FASE 2**  
> **Prioridad:** Alta (Cierre del Capítulo 5 de Seguridad Criptográfica, Autenticación y RBAC)  
> **Objetivo:** Implementar el mecanismo de Rate Limiting Defensivo y mitigación de ataques de fuerza bruta / credential stuffing sobre los endpoints críticos de autenticación (`/api/v1/auth/login`, `/api/v1/auth/register`, `/api/v1/auth/refresh`), devolviendo respuestas HTTP 429 (`Too Many Requests`) con cabecera `Retry-After` bajo el contrato `APIErrorResponse`.

### Hoja de Ruta Inmediata para el Capítulo 5:
1. **Módulo 5.4 (Fase 2)**: Implementar Rate Limiting Defensivo y Mitigación de Fuerza Bruta en `/auth`, junto con su suite de pruebas unitarias y de integración, cerrando el Capítulo 5 al 100%.

