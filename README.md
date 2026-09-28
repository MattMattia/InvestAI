# InvestAI — Plataforma de Gestión de Portafolios y Evaluación de Riesgo

> **Etapa 1: Trabajo de Campo & Motor de Riesgo Determinista**  
> Sistema de gestión de tenencias, valuación de activos (Renta Variable / Renta Fija) y control de riesgo financiero basado en reglas cuantitativas deterministas.

---

## 📌 1. Visión General del Proyecto

**InvestAI** es una plataforma orientada a inversores y asesores financieros para el seguimiento integral de carteras de inversión, control estricto de exposición al riesgo y optimización de posiciones.

En esta **Etapa 1 (Trabajo de Campo)**, el núcleo del sistema es **100% determinista** (sin modelos probabilísticos ni IA generativa/caja negra). Todas las decisiones, métricas de riesgo y sugerencias de rebalanceo están regidas por fórmulas matemáticas verificables, ratios contables y límites de control parametrizables.

---

## 🎯 2. Alcance Funcional — Etapa 1

### 2.1. Gestión e Ingesta de Portafolios
- **Carga Manual:** Alta, edición y baja de tenencias y transacciones por especie (Ticker, Cantidad, Precio de Compra, Moneda, Fecha).
- **Pipeline de Ingesta Universal & Saneamiento:** Parser universal desacoplado de planillas Excel (`.xlsx`) y archivos `.csv` con detección adaptativa de encabezados, soporte de decimales latinos, inferencia automática de especies y tolerancia a fallos por fila.

### 2.2. Activos Soportados
- **Renta Variable (Acciones Locales y CEDEARs):**
  - Manejo de ratios de conversión de CEDEARs (ej. Apple 10:1, SPY 20:1).
  - Cálculo de Dólar Implícito Contado con Liquidación ($CCL$) y Dólar MEP por activo y promedio ponderado:
    $$\text{Dólar CCL Ticker} = \frac{\text{Precio CEDEAR (ARS)} \times \text{Ratio CEDEAR}}{\text{Precio Subyacente (USD)}}$$
  - Ratios contables de valuación fundamental:
    - **$P/E$ (Price-to-Earnings Ratio):** $\frac{\text{Precio}}{\text{Beneficio por Acción}}$
    - **$P/B$ (Price-to-Book Ratio):** $\frac{\text{Precio}}{\text{Valor Libros por Acción}}$
    - **$PEG$ (Price/Earnings-to-Growth):** $\frac{P/E}{\text{Crecimiento EPS (\%) eb}}$
    - **Protección contra pérdidas:** Si $EPS \le 0$, el estado se etiqueta formalmente como `INDETERMINATE`.
- **Renta Fija (Bonos Soberanos / Subsoberanos / Obligaciones Negociables):**
  - Clasificación por tipo (Soberano, Corporativo, Letras del Tesoro).
  - Cálculo de ponderación de Renta Fija y exigencia de piso según perfil de inversor.

### 2.3. Motor de Reglas Determinista & Métricas Cuantitativas
1. **Límites de Concentración:**
   - Exposición máxima por activo individual (ej. máx 15% - 25% según perfil).
   - Exposición máxima por sector de la economía (ej. máx 30% - 40%).
   - Exposición por tipo de activo (Piso mínimo de Renta Fija según perfil conservador/moderado).
2. **Rebalanceo por Bandas de Tolerancia (Tolerance Band Rebalancing):**
   - Comparación entre la *Asignación Objetivo (Target)* y la *Asignación Actual*.
   - Generación de órdenes sugeridas de compra/venta deterministas cuando el desvío supera el umbral de tolerancia ($\vert w_i - w_i^* \vert > \tau_i$).
   - Truncamiento a nominales enteros y chequeo de conservación de liquidez en efectivo.
3. **Alertas de Valuación y Arbitraje FX:**
   - Detección de distorsiones en el tipo de cambio implícito entre CEDEARs y el dólar cable de referencia.
   - Banderas de alerta ante anomalías contables ($PEG > 2.0$, $P/B$ extremos o $EPS \le 0$).
4. **Métricas Cuantitativas de Portafolio:**
   - Rendimientos logarítmicos continuos, volatilidad histórica realizada anualizada ($N=252$), volatilidad matricial $\sqrt{\mathbf{w}^\mathsf{T} \boldsymbol{\Sigma} \mathbf{w}} \cdot \sqrt{252}$, Sharpe Ratio, Sortino Ratio, Maximum Drawdown (MDD) con Calmar Ratio y Value at Risk (VaR) paramétrico.

---

## 🏛️ 3. Arquitectura del Sistema

El sistema está estructurado bajo un enfoque de **Monolito Modular**, garantizando alta cohesión, bajo acoplamiento y facilidad de evolución.

```
InvestAI_Mattia_Risso/
├── backend/                        # API REST en FastAPI + Lógica de Dominio
│   ├── alembic/                    # Control de versiones y migraciones de BD
│   │   ├── versions/
│   │   │   └── 001_initial_schema.py # DDL inicial de 6 tablas relacionales
│   │   ├── env.py                  # Configuración asíncrona/síncrona de Alembic
│   │   └── script.py.mako
│   ├── app/
│   │   ├── api/                    # Controladores y Endpoints REST (FastAPI Routers)
│   │   │   ├── v1/
│   │   │   │   ├── endpoints/
│   │   │   │   │   ├── portfolios.py   # Gestión CRUD de carteras
│   │   │   │   │   ├── holdings.py     # Gestión de tenencias
│   │   │   │   │   ├── market_data.py  # Cotizaciones, ratios contables y FX
│   │   │   │   │   ├── risk.py         # Evaluación de riesgo y alertas
│   │   │   │   │   ├── imports.py      # Ingesta y parsing universal de archivos
│   │   │   │   │   └── rebalancing.py  # Generador de rebalanceo
│   │   │   │   └── router.py
│   │   │   └── deps.py             # Inyección de dependencias (DB Session, etc.)
│   │   ├── core/                   # Configuraciones globales, base de datos y logging
│   │   │   ├── config.py           # Variables de entorno con Pydantic Settings
│   │   │   ├── database.py         # Engine y SessionFactory de SQLAlchemy 2.0
│   │   │   └── exceptions.py       # Excepciones de dominio y API Handlers
│   │   ├── domain/                 # Lógica Pura de Negocio (Zero Frameworks)
│   │   │   ├── models/             # Entidades de dominio y Value Objects
│   │   │   │   ├── asset.py        # Asset, AssetType, Currency, Sector
│   │   │   │   ├── portfolio.py    # Holding, Portfolio, InvestorProfile
│   │   │   │   ├── valuation.py    # ValuationMetrics, ValuationStatus
│   │   │   │   └── metrics.py      # Volatilidad, Sharpe, Sortino, MDD, VaR
│   │   │   └── rules/              # Motor de Reglas de Riesgo Determinista
│   │   │       ├── base.py         # Clase abstracta BaseRiskRule, RuleResult, Severity
│   │   │       ├── concentration.py# Reglas de concentración por activo y sector
│   │   │       ├── fixed_income.py # Regla de piso mínimo en Renta Fija
│   │   │       ├── valuation.py    # Regla de ratios P/E, P/B, PEG
│   │   │       ├── fx_ccl.py       # Regla de desvío CCL/MEP
│   │   │       ├── rebalancing.py  # Algoritmo de rebalanceo por bandas
│   │   │       └── engine.py       # Orquestador RiskEngine y auditoría
│   │   ├── models/                 # Modelos ORM (SQLAlchemy 2.0 Declarative)
│   │   │   ├── user.py             # UserModel (users)
│   │   │   ├── asset.py            # AssetModel (assets)
│   │   │   ├── portfolio.py        # PortfolioModel (portfolios)
│   │   │   ├── holding.py          # HoldingModel (holdings)
│   │   │   ├── risk_audit.py       # RiskAuditSnapshotModel (risk_audit_snapshots)
│   │   │   └── rebalance_order.py  # RebalanceOrderModel (rebalance_orders)
│   │   ├── schemas/                # Data Transfer Objects (DTOs con Pydantic v2)
│   │   │   └── ingestion.py        # RawHoldingRecord, IngestionBatchPayload
│   │   ├── services/               # Servicios de Aplicación y Parsers
│   │   │   └── parsers/            # Pipeline de Ingesta Universal
│   │   │       └── universal_parser.py # UniversalHoldingParser e IngestionReport
│   │   └── main.py                 # Punto de entrada de la aplicación FastAPI
│   ├── tests/                      # Suite de tests automatizados (Pytest/Unittest)
│   │   ├── unit/                   # Tests unitarios del Rule Engine, Métricas, ORM
│   │   │   ├── test_domain_models.py
│   │   │   ├── test_rules.py
│   │   │   ├── test_metrics.py
│   │   │   ├── test_rebalancing.py
│   │   │   ├── test_ingestion.py
│   │   │   └── test_persistence_models.py
│   │   ├── integration/            # Tests de integración con base de datos y API
│   │   └── conftest.py
│   ├── Dockerfile
│   ├── pyproject.toml
│   └── requirements.txt
├── frontend/                       # Frontend SPA en React + Vite + TypeScript
│   ├── src/
│   │   ├── components/             # Componentes modulares (Tablas, Métricas, Upload)
│   │   ├── pages/                  # Vistas principales (Dashboard, Portafolio, Riesgo)
│   │   ├── services/               # Clientes HTTP (Axios / Fetch a la API)
│   │   ├── types/                  # Definiciones de tipos TypeScript
│   │   ├── App.tsx
│   │   └── main.tsx
│   ├── Dockerfile
│   ├── package.json
│   └── vite.config.ts
├── docker-compose.yml              # Orquestación de Backend, Frontend y PostgreSQL 15
├── alembic.ini                     # Configuración de migraciones Alembic
├── .env.example                    # Plantilla de variables de entorno
├── .gitignore
└── README.md
```

---

## 🛠️ 4. Stack Tecnológico

| Capa | Tecnología | Propósito |
| :--- | :--- | :--- |
| **Backend** | Python 3.11+ / FastAPI | API REST asíncrona de alto rendimiento y tipado estricto |
| **Validación & DTOs** | Pydantic v2 | Validación de esquemas, configuración y serialización |
| **ORM & Migraciones** | SQLAlchemy 2.0 + Alembic | Mapeo relacional estructurado y versionado de base de datos |
| **Base de Datos** | PostgreSQL 15 | Persistencia relacional de transacciones, portafolios y reglas |
| **Frontend** | React 18+ / TypeScript / Vite | Interfaz de usuario dinámica, visualización de métricas y carga |
| **Testing** | Pytest / Unittest | Pruebas unitarias de cobertura exhaustiva (100% passing) |
| **Infraestructura** | Docker & Docker Compose | Contenerización y ejecución reproducible en entornos locales/prod |

---

## 🚀 5. Puesta en Marcha

### Prerrequisitos
- [Docker](https://docs.docker.com/get-docker/) y [Docker Compose](https://docs.docker.com/compose/install/) instalados.
- Python 3.11+ y Node.js 18+ (opcional para desarrollo local sin Docker).

### Ejecución con Docker Compose (Recomendado)
1. **Configurar variables de entorno:**
   ```bash
   cp .env.example .env
   ```
2. **Construir y levantar contenedores:**
   ```bash
   docker compose up --build -d
   ```
3. **Acceso a los servicios:**
   - **Frontend Dashboard:** `http://localhost:5173`
   - **Backend API:** `http://localhost:8000`
   - **Documentación Swagger / OpenAPI:** `http://localhost:8000/docs`
   - **PostgreSQL:** `localhost:5432`

---

## 📐 6. Calidad de Código y Convenciones

- **Tipado Estricto (Type Hints):** 100% del código en Python incluye anotaciones de tipo validadas con `mypy` / `ruff`.
- **Manejo Explícito de Excepciones:** Errores de parsing o validación de riesgo devuelven respuestas estructuradas con códigos de error claros.
- **Pattern Rule Engine:** Nuevas reglas de riesgo pueden añadirse implementando la interfaz `BaseRiskRule` sin modificar el código existente (Principio Open/Closed de SOLID).
- **Arquitectura Limpia & Desacoplada:** El dominio puro no tiene dependencias de bases de datos ni frameworks web. Los modelos ORM se mapean explícitamente hacia las entidades de negocio.

---

## 📊 7. Estado de Implementación — Módulo Base & Risk Management

| Componente | Archivo | Estado | Descripción |
| :--- | :--- | :---: | :--- |
| **Configuración Core** | `backend/app/core/config.py` | ✅ | `Settings` tipado con Pydantic v2 Settings, URIs async/sync y límites de control. |
| **Persistencia Asíncrona** | `backend/app/core/database.py` | ✅ | Engine asíncrono SQLAlchemy 2.0 (`asyncpg`), `AsyncSessionLocal` y `get_async_db`. |
| **Modelos de Activos** | `backend/app/domain/models/asset.py` | ✅ | Dataclasses y Enums para `AssetType`, `Currency`, `Sector` y `Asset` con ratios CEDEAR. |
| **Portafolio y Tenencias** | `backend/app/domain/models/portfolio.py` | ✅ | `Holding` y `Portfolio` con consolidación multimoneda ARS/USD y cálculo de pesos %. |
| **Valuación Fundamental** | `backend/app/domain/models/valuation.py` | ✅ | $P/E, P/B, PEG$ y tratamiento de $EPS \le 0 \rightarrow$ Estado `INDETERMINATE`. |
| **Métricas Cuantitativas** | `backend/app/domain/models/metrics.py` | ✅ | Log returns, volatilidad realizada/matricial, Sharpe, Sortino, MDD, VaR paramétrico. |
| **Base Rule Engine** | `backend/app/domain/rules/base.py` | ✅ | Interfaz abstracta `BaseRiskRule`, `RuleResult` y niveles de `Severity`. |
| **Orquestador de Riesgo** | `backend/app/domain/rules/engine.py` | ✅ | `RiskEngine` con evaluación desacoplada y snapshots de auditoría `RiskAssessmentReport`. |
| **Regla Concentración Activo/Sector** | `backend/app/domain/rules/concentration.py` | ✅ | `MaxAssetConcentrationRule` y `MaxSectorConcentrationRule` con límites por perfil. |
| **Regla Asignación Renta Fija** | `backend/app/domain/rules/fixed_income.py` | ✅ | `MinFixedIncomeAllocationRule` para control del piso de bonos según perfil. |
| **Regla Anomalías de Valuación** | `backend/app/domain/rules/valuation.py` | ✅ | `ValuationAnomalyRule` ($PEG > 2.0$, $P/B$ anómalos y empresas con pérdidas $EPS \le 0$). |
| **Regla Brecha Dólar Implícito** | `backend/app/domain/rules/fx_ccl.py` | ✅ | `ImplicitFXDivergenceRule` para arbitraje y desvío cambiario $CCL/MEP$. |
| **Rebalanceo por Bandas** | `backend/app/domain/rules/rebalancing.py` | ✅ | `ToleranceBandRebalancer` con órdenes BUY/SELL/HOLD, nominales enteros y liquidez. |
| **Contrato de Ingesta** | `backend/app/schemas/ingestion.py` | ✅ | DTOs inmutables `RawHoldingRecord` e `IngestionBatchPayload` con validación estricta. |
| **Pipeline de Ingesta Universal** | `backend/app/services/parsers/universal_parser.py` | ✅ | `UniversalHoldingParser` tolerante a fallos, soporte CSV/Excel, decimales latinos y mapping. |
| **Modelos Relacionales ORM** | `backend/app/models/` | ✅ | Mapeo SQLAlchemy 2.0 Declarative: `users`, `assets`, `portfolios`, `holdings`, `risk_audit_snapshots`, `rebalance_orders`. |
| **Control de Migraciones** | `backend/alembic/` | ✅ | Entorno de migraciones Alembic configurado y migración inicial `001_initial_schema.py`. |
| **Suite Completa de Tests (Inicial)** | `backend/tests/unit/` | ✅ | **49 de 49 tests aprobados al 100%** (Dominio, Métricas, Reglas, Rebalanceo, Ingesta, Persistencia). |

---

## 🔬 8. Módulos Cuantitativos Avanzados (Módulos 1 al 5)

### 8.1. Modelos Financieros y Valoración Fundamental Base
- **Estados Financieros Canónicos (`backend/app/domain/models/financial_statements.py`):**
  - Implementación inmutable bajo estándar OpenBB: `IncomeStatementStandard`, `BalanceSheetStandard`, `CashFlowStandard` y `KeyMetricsStandard`.
  - Síntesis automática de Deuda Neta ($\text{Deuda Total} - \text{Caja}$) y Patrimonio Neto ($\text{Activos} - \text{Pasivos}$).
  - Cálculo determinista de Free Cash Flow ($\text{FCF} = \text{Flujo Operativo} - |\text{CapEx}|$).
  - Ratios contables calculados de forma segura con protección estricta contra división por cero (`safe_divide`): ROE, Current Ratio, Debt to Equity, EV/EBITDA, P/E, P/B y PEG.
  - Saneamiento automático de entradas corruptas, valores `NaN`, `Inf` y cadenas con formatos monetarios (`clean_financial_float`).
  - Tratamiento formal de empresas con pérdidas: cuando $EPS \le 0$, los múltiplos basados en beneficios se clasifican formalmente bajo `ValuationStatus.INDETERMINATE`.

### 8.2. Módulo 1: Estandarización Canónica, Bimoneda y Calendarios Bursátiles
- **Normalización Bimonetaria y Dólar Implícito (`backend/app/domain/services/fx_service.py`):**
  - Modelado de divisas canónicas: `Currency.ARS`, `Currency.USD`, `Currency.USD_MEP`, `Currency.USD_CCL`.
  - Cálculo determinista de tipo de cambio implícito para instrumentos dual-listed (CEDEARs):
    $$\text{CCL}_{\text{implícito}} = \frac{\text{Precio CEDEAR (ARS)} \times \text{Ratio de Conversión}}{\text{Precio Subyacente (USD)}}$$
  - Conversión canónica entre cualquier par de monedas con normalización cruzada.
- **Sincronización de Calendarios Bursátiles (`backend/app/domain/services/calendar_service.py`):**
  - Detección de sesiones activas y feriados bancarios/bursátiles para BYMA (Buenos Aires) y NYSE/NASDAQ (Estados Unidos) para el período 2024–2027.
  - Algoritmo de **Forward-Fill determinista**: ante feriados asimétricos entre plazas, preserva el último precio conocido, marca el estado `QuoteState.STALE_MARKET_CLOSED` con explicación auditable y recalcula el CCL implícito resultante.

### 8.3. Módulo 2: Optimización Matemática de Carteras y Riesgo de Cola
- **Estimación de Covarianza Robusta (`backend/app/domain/services/quantitative_risk.py`):**
  - Contracción analítica de Ledoit-Wolf (2004) hacia matriz identidad escalada ($F = \mu I_N$):
    $$\boldsymbol{\Sigma}^* = (1 - \delta^*) \mathbf{S} + \delta^* \mathbf{F}, \quad \delta^* \in [0, 1]$$
  - Garantiza matrices simétricas, bien condicionadas y **estrictamente definidas positivas e invertibles** aun bajo rangos deficientes ($T < N$) o activos fuertemente colineales.
- **Algoritmos de Optimización de Asignación (`backend/app/domain/services/portfolio_optimizer.py`):**
  - **Global Minimum Variance (GMV):** Minimización cuadrática SLSQP de volatilidad de cartera sujeta a restricciones long-only ($\sum w_i = 1, w_i \ge 0$).
  - **Risk Parity / Equal Risk Contribution (ERC):** Igualación de la contribución marginal de riesgo de cada activo ($RC_i = \sigma_p / N$), resuelto mediante la formulación estrictamente convexa de Spinu (2013) con gradiente analítico $\boldsymbol{\Sigma} \mathbf{y} - \mathbf{y}^{-1}$.
  - **Ratio de Diversificación (Choueifaty & Coignard, 2008):**
    $$DR(\mathbf{w}) = \frac{\sum_{i=1}^N w_i \sigma_i}{\sqrt{\mathbf{w}^\mathsf{T} \boldsymbol{\Sigma} \mathbf{w}}} \ge 1.0$$
- **Métricas de Distribución y Riesgo de Cola:**
  - Asimetría (Skewness) y Exceso de Curtosis para cuantificar leptocurtosis y riesgo de caídas asimétricas.
  - Value at Risk (VaR) histórico y paramétrico gaussiano a niveles de confianza parametrizables ($\alpha = 0.95, 0.99$).
  - Conditional Value at Risk / Expected Shortfall (CVaR) con garantía teórica $\text{CVaR}_\alpha \ge \text{VaR}_\alpha$.
- **Endpoints REST (`backend/app/api/v1/endpoints/optimization.py`):**
  - `POST /api/v1/portfolios/{id}/optimize/minimum-variance`: Optimización GMV sobre tenencias reales o matriz de retornos.
  - `POST /api/v1/portfolios/{id}/optimize/risk-parity`: Optimización ERC equilibrando presupuesto de riesgo por activo.
  - `POST /api/v1/portfolios/{id}/tail-risk`: Auditoría de momentos estadísticos y pérdidas de cola de la cartera actual.

### 8.4. Módulo 3: Estabilidad Numérica Avanzada y Cadenas de Markov
- **Álgebra Lineal Robusta (`backend/app/domain/services/numerical_stability.py`):**
  - `safe_cholesky`: Descomposición de Cholesky $\mathbf{L}$ ($\mathbf{A} = \mathbf{L} \mathbf{L}^\mathsf{T}$) con regularización diagonal iterativa (*jitter*) y proyección espectral de Higham (1988/2002) ante matrices singulares o no definidas positivas.
  - `safe_pinv`: Pseudoinversa de Moore-Penrose estable mediante descomposición SVD truncada con tolerancia numérica `rcond`.
  - `nearest_positive_definite` y `matrix_condition_number` ($\kappa(A) = \sigma_{\max}/\sigma_{\min}$).
  - Validación defensiva temprana contra valores `NaN` e `Infinitos` en todas las operaciones tensoriales.
- **Modelado de Regímenes de Mercado con Cadenas de Markov (`backend/app/domain/services/markov_regime.py`):**
  - Modelo de cambio de régimen de 2 estados:
    - Estado 0: `LOW_VOLATILITY` (Régimen de Expansión / Estabilidad).
    - Estado 1: `HIGH_VOLATILITY` (Régimen de Turbulencia / Crisis).
  - Matriz de transición estocástica ($P_{ij}$), calibración por máxima verosimilitud con suavizado de Laplace y distribución ergódica estacionaria.
  - **Bandas Dinámicas de Rebalanceo (`get_dynamic_rebalance_band`):**
    - En **Baja Volatilidad:** Estrecha la banda al $85\%$ ($0.85\times$) del valor base para un seguimiento ceñido con fricción mínima.
    - En **Alta Volatilidad / Crisis:** Amplía la banda al $175\%$ ($1.75\times$) para evitar *whipsaw* y costos transaccionales excesivos ante ruido transitorio.

### 8.5. Módulo 4: FSM de Órdenes y Fricciones de Mercado
- **Máquina de Estados Finitos (FSM) de Órdenes (`backend/app/domain/models/order.py`):**
  - Estados formales (`OrderState`): `CREATED`, `VALIDATED`, `SUBMITTED`, `FILLED`, `CANCELLED`, `REJECTED`.
  - Grafo estricto de transiciones:
    $$\text{CREATED} \longrightarrow \text{VALIDATED} \longrightarrow \text{SUBMITTED} \longrightarrow \text{FILLED}$$
    con derivaciones a `CANCELLED` y `REJECTED`, e inmutabilidad estricta de estados terminales (`InvalidOrderStateTransitionError`).
  - Entidad `Order` (Pydantic v2) con validación cruzada: las órdenes `LIMIT` exigen precio positivo obligatorio, con normalización automática de tickers.
- **Motor Cuantitativo de Fricciones de Mercado (`backend/app/domain/services/market_frictions.py`):**
  - `calculate_alyc_commission`: Comisión de ALyC sobre volumen efectivo con arancel mínimo e IVA ($21\%$).
  - `calculate_market_fees`: Derechos de mercado y aranceles de compensación BYMA/CNV (default $0.09\%$).
  - `calculate_slippage`: Deslizamiento asimétrico según el sentido de la orden (precio adverso al alza en `BUY`, precio adverso a la baja en `SELL`).
  - `calculate_net_execution_cost`: Desglose completo en `ExecutionCostBreakdown`:
    - Compras (`BUY`): $\text{Desembolso Neto} = \text{Monto Efectivo} + \text{Comisiones} + \text{IVA} + \text{Aranceles}$
    - Ventas (`SELL`): $\text{Fondos Netos Recibidos} = \text{Monto Efectivo} - (\text{Comisiones} + \text{IVA} + \text{Aranceles})$
    - Cálculo de precio neto por acción y porcentaje total de fricción.

### 8.6. Módulo 5: Motor de Backtesting Histórico y Simulación Vectorizada
- **Esquemas Canónicos e Inmutables (`backend/app/schemas/backtest.py`):**
  - Frecuencias de rebalanceo (`RebalanceFrequency`): `DAILY`, `WEEKLY`, `MONTHLY`, `QUARTERLY`.
  - Configuración y solicitud (`BacktestConfig`, `BacktestRunRequest`): Capital inicial, tickers normalizados, fechas de inicio/fin, tasa libre de riesgo y configuración detallada de fricciones de intermediación (`BacktestFrictionConfig`).
  - Snapshots diarios inmutables (`DailySnapshot`): Registro diario de NAV, caja disponible, nominales por especie, retorno porcentual diario y *drawdown* relativo acumulado.
  - Resultados consolidados (`BacktestPerformanceMetrics`, `BacktestResult`): Métricas de rendimiento ajustado por riesgo, serie temporal completa y auditoría de órdenes ejecutadas.
- **Servicio Cuantitativo de Métricas Financieras (`backend/app/domain/services/backtest_metrics.py`):**
  - Programación defensiva con saneamiento preventivo ante valores `NaN`, `Inf` o divisiones por cero.
  - Retorno Total acumulado y CAGR:
    $$\text{CAGR} = \left(\frac{V_N}{V_0}\right)^{\frac{252}{N}} - 1$$
  - Volatilidad realizada anualizada ($\sigma_{\text{diaria}} \times \sqrt{252}$).
  - Ratios de Sharpe y Sortino anualizados: evaluación rigurosa del desvío bajista (*downside deviation*) respecto al umbral diario de la tasa libre de riesgo $\tau = r_f / 252$.
  - Serie temporal de *drawdowns* ($DD_t = (V_t - \text{Peak}_t) / \text{Peak}_t \le 0.0$) y Máximo Drawdown en magnitud absoluta ($\text{MDD} \ge 0.0$).
  - Ratio de Calmar determinista ($\text{Calmar} = \text{CAGR} / |\text{MDD}|$) con protección total ante ausencias de caídas pico a valle.
- **Motor de Simulación Temporal (`backend/app/domain/services/backtest_engine.py`):**
  - Bucle de simulación día a día sincronizado con el calendario bursátil de días hábiles.
  - Rebalanceo periódico por frecuencia con asignación de cartera inicial obligatoria en $t=0$.
  - Optimización de cartera (GMV vía `minimum_variance_portfolio` o ERC vía `risk_parity_portfolio`) sobre ventana móvil (`lookback_window=60`) con contracción de covarianza de Ledoit-Wolf (`ledoit_wolf_covariance`), y *fallback* a equiponderación ($1/N$).
  - Prioridad de liquidez: ejecución de ventas en primer término para acreditar efectivo, seguido de compras con restricción estricta de saldo de caja para absorber comisiones y costos.
  - Integración total con la Máquina de Estados Finitos (FSM) de órdenes (`CREATED` $\to$ `VALIDATED` $\to$ `SUBMITTED` $\to$ `FILLED`) y cálculo determinista de fricciones netas con `calculate_net_execution_cost`.
- **Endpoint REST Institucional (`backend/app/api/v1/endpoints/backtest.py`):**
  - `POST /api/v1/backtest/run`: Ejecución integral de backtesting desde el cliente o frontend.
  - Generador estocástico continuo de Movimiento Browniano Geométrico (GBM):
    $$dS_t = \mu S_t dt + \sigma S_t dW_t$$
    con factor de correlación sistémica de mercado ($\rho = 0.35$) y dinámicas empíricas parametrizadas por tipo de especie (bonos soberanos, renta variable local y CEDEARs).
  - Soporte bimodal: síntesis autónoma sobre el rango de fechas o ingesta de cotizaciones históricas provistas por el usuario.

---

## 🛡️ 9. Calidad de Software, Ingeniería y Testing

- **Pydantic v2 Estricto:** Todos los modelos usan `ConfigDict(frozen=True)` o `ConfigDict(from_attributes=True)` y validadores `@field_validator` / `@model_validator`.
- **Saneamiento Completo de Código Fuente:** El 100% de los archivos del backend carecen de caracteres BOM (`\xef\xbb\xbf`), código muerto o importaciones huérfanas, verificado por análisis de árbol sintáctico (AST).
- **Aislamiento Arquitectónico:** Los modelos de dominio puro nunca dependen de SQLAlchemy ni de la infraestructura web.
- **Suite de Pruebas Automatizadas (100% Passing):**
  ```powershell
  $env:PYTHONPATH = "backend"; python -m unittest discover -s backend/tests/unit
  $env:PYTHONPATH = "backend"; python -m unittest discover -s backend/tests/integration
  ```
  - **121 pruebas unitarias** (Modelos de Dominio, Reglas, Métricas, Rebalanceo, Persistencia, Ingesta, Bimoneda, Calendarios, Optimización, Markov, Estabilidad Numérica, FSM/Fricciones y Métricas de Backtest).
  - **16 pruebas de integración** (Base de datos relacional, endpoints REST, motor de simulación temporal BacktestEngine y endpoint /backtest/run).
  - **Total: 137 pruebas ejecutadas con éxito en ~2.2 segundos.**

---

## 🔮 10. Roadmap de Expansión (Próximas Etapas)

- **Módulo 5 — Motor de Backtesting Histórico y Simulación:** ✅ **Completado al 100%**
  - Fase 1: Esquemas de configuración, snapshots y servicio cuantitativo de métricas financieras.
  - Fase 2: Motor de simulación cronológica (`BacktestEngine`) con bucle de rebalanceo, optimización Ledoit-Wolf, FSM y fricciones.
  - Fase 3: Endpoint REST `/api/v1/backtest/run` con simulación por Movimiento Browniano Geométrico (GBM).
- **Módulo 6 — Conectores de Datos en Vivo e Ingesta de Mercado:**
  - Integración de feeds de mercado en tiempo real (Matba Rofex / Primary API, BYMA DMA, OpenBB / Yahoo Finance).
  - Cache distribuido en Redis con TTL adaptativo para evitar sobreconsultas a proveedores de cotización.
- **Módulo 7 — Orquestación Multi-Agent y LLMOps:**
  - Implementación de agentes de IA especializados con llamadas a funciones (`function calling`) deterministas sobre los servicios cuantitativos ya construidos.
  - Agente Asesor de Asignación, Agente Auditor de Compliance y Agente Analista Fundamental con generación automatizada de informes en PDF.
- **Módulo 8 — Dashboard Frontend Institucional:**
  - Visualización avanzada de superficies de volatilidad, curvas de rendimiento, simulador de rebalanceo interactivo y matriz de correlación en tiempo real en React/Vite.

