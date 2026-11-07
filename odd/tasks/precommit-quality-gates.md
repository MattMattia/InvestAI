# Pre-commit quality gates

## Objective
Make `pre-commit run --all-files` pass fully with Biome (frontend), Ruff (backend), gitleaks and standard hygiene hooks.

## Done by parent
- `biome.json` (Biome 2.6.6, migrated to `"preset": "recommended"`; 2-space, lineWidth 100, LF; `useImportType` error; 8 rules at warn; tailwind directives).
- `ruff.toml` (py311, line 100, `E,W,F,I,B,UP,S`, ignore `E501,B008,S101`).
- `.pre-commit-config.yaml`; `pre-commit` 4.7.0 installed via uv; `pre-commit install` (existing GGA hook kept as `.git/hooks/pre-commit.legacy`, migration mode).
- Auto-fixers applied (whitespace, EOF, LF, ruff --fix, ruff-format, biome --write). Backend `pytest`: 674 passed after auto-fixes.

## Remaining after 2nd run
- Ruff (hook v0.9.6): 84 — UP038 20, S106 15, S105 11, B904 9, S110 7, F821 7, S311 4, S112 2, E731 2, B007 2, S104 1, F841 1, F401 1, E741 1, E402 1.
- Biome: 11 errors — useExhaustiveDependencies 5, noSvgWithoutTitle 3, noUnknownAtRules 3 (index.css).

## Tasks
- [x] T1 Fix remaining Ruff violations in `backend/` (real fixes first; scoped `per-file-ignores` for tests; justified `# noqa` only for false positives).
- [x] T2 Fix remaining Biome errors in `frontend/src`.
- [x] T3 `pre-commit run --all-files` all Passed; pytest and tsc green.
- [x] T4 Document tooling in `CLAUDE.md` (parent; parent spot check: all 11 hooks Passed, pytest 674 passed, tsc exit 0).

Route: delegated direct (one writer). TDD: off; functional checks: pytest (backend), tsc (frontend).

## Checks
- `pre-commit run --all-files` (repo root): every hook Passed.
- `cd backend && PYTHONPATH=. python -m pytest -q -p no:cacheprovider`: all pass (baseline 674).
- `cd frontend && npx --no-install tsc --noEmit`: exit 0.

## Progress
Writer run complete (uncommitted).
- `pre-commit run --all-files`: all 11 hooks Passed (stable on 2nd run; ruff, ruff-format, biome check included).
- pytest: 674 passed. `tsc --noEmit`: exit 0.
- Real bugs fixed: `config.py` missing `import concurrent.futures` (NameError in probe, masked by broad except -> always False); `metrics.py` `QuantitativeRiskSummary` forward ref (`from __future__ import annotations`); `test_alembic_lifecycle.py` missing `Any` import; B904 exception chaining (`from None` for token errors, `from exc` elsewhere); `except: pass` now logs at debug.
- Cleanups: UP038 -> `A | B`; removed dead `f_high` (portfolio_valuation_service); E731 lambdas -> defs; B007/E741 renames; E402 import moved to top in `main.py`.
- Suppressions: ruff.toml per-file-ignores (`backend/tests/**`: S105,S106,S311; `backend/scripts/seed*.py`: S105,S106). noqa: S105 config.py (SECRET_KEY, POSTGRES_PASSWORD dev defaults), S106 security.py (token_type="bearer"), S104 ssrf_guard (blocklist "0.0.0.0"), S112 metrics.py (route matching), S311 market_data_provider (simulated ticks/volume), F401 tests/conftest.py (availability probe).
- Biome: svg `<title>` added (3); `useExhaustiveDependencies`: AllocationChart `round2` moved to module scope, AuthModal `resetFormState`/`handleClose` wrapped in useCallback; 2 justified biome-ignore (AuthModal `isAuthenticated`, FinancialTimeSeriesChart `activeTicker`, intentional reset triggers). index.css noUnknownAtRules not in hook scope (css not in types_or), left as is.
