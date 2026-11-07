# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

InvestAI: portfolio management and deterministic risk-evaluation platform for the Argentine market (BYMA, bi-currency ARS/USD, CEDEARs, local brokers Balanz/IOL/PPI). FastAPI backend + React/Vite/TypeScript SPA. The risk core is intentionally **100% deterministic** — no probabilistic/generative models in decision logic; every metric and rebalancing suggestion must come from verifiable formulas.

Docs and UI copy are largely in Spanish. Code comments and docstrings cite audit/requirement IDs (e.g. `SEC-01`, `ARQ-02`, `OBS-02`, "Módulo 8.3") tracked in `docs/AUDIT_LEDGER.md`, `docs/MASTER_PLAN.md`, and `docs/PROGRESS.md`. Keep those references when editing.

## Commands

Backend (run from `backend/`, `PYTHONPATH` must point at `backend/`):

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
pytest                                   # full suite (testpaths=tests, asyncio_mode=auto)
pytest -m unit                           # or -m integration
pytest tests/unit/test_rules.py::TestX::test_y   # single test
alembic upgrade head                     # migrations (alembic.ini lives in backend/)
python scripts/seed_smoke_test.py        # seed data for smoke testing
```

Frontend (run from `frontend/`):

```bash
npm run dev        # Vite on :5173, proxies /api, /health, /ready, /metrics to 127.0.0.1:8000
npm run build      # tsc type-check + vite build (this is the only type/lint gate)
```

Full stack: `start_app.ps1` / `start_app.bat` (frees ports 8000/5173, starts both), `scripts/stop_investai.ps1` to stop, or `docker compose up` (Postgres 15 + backend + frontend).

## Architecture

### Database: Postgres with automatic SQLite fallback
`app/core/config.py` probes Postgres at startup; if unreachable and `USE_SQLITE_FALLBACK=True`, `ASYNC_DATABASE_URI` silently switches to `sqlite+aiosqlite:///./investai_dev.db`. `DATABASE_URL` overrides both. `init_db()` in `app/core/database.py` runs `Base.metadata.create_all` on lifespan startup and applies ad-hoc SQLite column migrations — so schema changes need both an Alembic revision and awareness of this SQLite path. Models are discovered via `import app.models`; any new ORM model must be re-exported from `app/models/__init__.py` or it won't be created.

### Backend layering (`backend/app/`)
- `domain/` — pure business logic, framework-free. `domain/models` (value objects: asset, portfolio, order FSM, FX, calendar), `domain/rules` (`BaseRiskRule` subclasses orchestrated by `RiskEngine` in `engine.py`), `domain/services` (quant engine: optimizer, backtest, Markov regime, technical indicators, tolerance-band rebalancer, market connector/scheduler, valuation, reconciliation, ingestion pipeline).
- `infrastructure/` — `db/` (newer ORM models like `MarketBarModel`, user) and `market_data/` (HTTP connector, quote cache, `ssrf_guard.py` — outbound market fetches must go through it).
- `models/` — legacy-location SQLAlchemy ORM models; `app/models/__init__.py` is the single aggregation point for both ORM locations and defines aliases (`OrderModel = RebalanceOrderModel`, `AuditLogModel = RiskAuditSnapshotModel`).
- `services/` — application services (`portfolio_service.py`, broker `parsers/`). Note `fx_service.py` and `calendar_service.py` exist both here and in `domain/services/`; check which one the caller imports before editing.
- `api/v1/endpoints/` — routers aggregated in `api/v1/router.py`, mounted at `/api/v1`. DI in `api/deps.py` (`get_db_session`, auth). `api/middleware/trace.py` sets request IDs.
- `core/` — settings, DB engine, JWT/crypto (`security.py`), rate limiting, Prometheus metrics (`/metrics`, optional scrape token).

### API contract
All errors are normalized in `main.py` exception handlers into the `APIErrorResponse` envelope (`app/schemas/envelope.py`: `success`, `error{code,message,details}`, `meta{request_id}`). 5xx messages are sanitized. New endpoints should use the envelope schemas rather than ad-hoc dicts.

### Tests
`tests/conftest.py` provides an in-memory SQLite `test_engine`, a `db_session`, and an `async_client` (httpx) that overrides `get_db_session` via `app.dependency_overrides`. Integration tests use these fixtures; no Postgres needed.

### Frontend (`frontend/src/`)
TanStack Query + axios. HTTP goes through `lib/apiClient.ts` (auth token handling via `lib/authStorage.ts`), wrapped by per-domain `services/*Service.ts`; query keys centralized in `lib/queryKeys.ts`; auth state in `context/AuthContext.tsx` + `hooks/useAuth.ts`. `@` alias → `src/`. Tailwind for styling.

## Architectural Rules & Target Standards

Strict rules for all new code and refactors:

1. **Domain & Services:** All new FX or calendar logic goes in `app/domain/services/`. Do not add new code to the legacy `app/services/fx_service.py` or `app/services/calendar_service.py`.
2. **Database & Migrations:** Every schema change ships as an Alembic migration (`backend/alembic/versions/`), with models written in SQLAlchemy 2.0 typed style (`Mapped[...]` / `mapped_column`). Do not add new manual SQLite column patches to `init_db()` in `app/core/database.py`.
3. **Security & Envelopes:** All outbound external calls must go through `app/infrastructure/market_data/ssrf_guard.py`. All error responses must use the `APIErrorResponse` envelope (`app/schemas/envelope.py`).
4. **Memory:** Check Engram for prior architectural decisions before making structural changes, and record new ones there. Keep the CodeGraph index (`.codegraph/`) current. The watcher syncs it automatically; run `codegraph sync` only if it reports stale files.
