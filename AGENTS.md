# Code Review Rules

Full project context lives in `CLAUDE.md`. These are the rules every commit is reviewed against.

## Backend (Python / FastAPI)
- New FX or calendar logic goes in `backend/app/domain/services/`, never in the legacy `backend/app/services/`.
- `backend/app/domain/` stays framework-free (no FastAPI, SQLAlchemy, or HTTP imports).
- Schema changes ship as an Alembic migration; ORM models use SQLAlchemy 2.0 typed style (`Mapped[...]` / `mapped_column`). No new manual SQLite column patches in `init_db()`.
- New ORM models must be re-exported from `backend/app/models/__init__.py`.
- Outbound HTTP calls go through `app/infrastructure/market_data/ssrf_guard.py`.
- Error responses use the `APIErrorResponse` envelope (`app/schemas/envelope.py`); 5xx messages must not leak internals.
- Risk, rebalancing, and valuation logic must stay deterministic (no randomness or ML models in decision paths).

## Frontend (React / TypeScript)
- No `any`; use `unknown` with narrowing or a specific type from `src/types/`.
- Every `<button>` declares an explicit `type`.
- List keys use stable domain identifiers, never array indexes.
- Accessibility: labels are bound to controls (`htmlFor` + `id`, via `useId()` in reusable components); interactive elements are semantic (`<button>`, not clickable `<div>`).
- HTTP goes through `src/lib/apiClient.ts` and per-domain `src/services/*`; server state through TanStack Query with keys from `src/lib/queryKeys.ts`.
- Code passes `biome check` formatting and `tsc --noEmit`.

## Commits
- Conventional Commits. Formatting-only changes go in their own commit, separate from behavior changes.
