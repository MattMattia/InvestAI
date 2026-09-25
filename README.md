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
| **Suite Completa de Tests** | `backend/tests/unit/` | ✅ | **49 de 49 tests aprobados al 100%** (Dominio, Métricas, Reglas, Rebalanceo, Ingesta, Persistencia). |
