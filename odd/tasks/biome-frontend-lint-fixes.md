# Biome frontend lint fixes

## Objective
Resolve the Biome lint diagnostics requested by the user in `frontend/src`.

## Baseline (2026-11-07, Biome 2.6.6, `biome lint frontend/src`)
119 errors, 34 warnings, 10 infos. In scope:
- `a11y/useButtonType` — 32
- `suspicious/noExplicitAny` — 20
- `suspicious/noArrayIndexKey` — 12
- `a11y/noLabelWithoutControl` — 35
- `a11y/noStaticElementInteractions` — 16
- `a11y/useKeyWithClickEvents` — 11
- `a11y/useSemanticElements` — 2

Out of scope (not requested): useExhaustiveDependencies, noUnknownAtRules, useOptionalChain, noSvgWithoutTitle, noNonNullAssertion, noGlobalIsNan, infos.

## Constraints
- No behavior or visual changes; preserve Tailwind classes and handlers.
- Keys must use stable domain identifiers (ticker, id, timestamp, etc.).
- `tsc --noEmit` must stay green (baseline: exit 0).
- Working tree already holds uncommitted Biome formatting across 54 files (user's change); not committed by this task.

## Tasks
- [x] T1 `useButtonType`: add `type="button"` (or `submit` where it submits a form).
- [x] T2 `noExplicitAny`: replace `any` with `unknown` + narrowing or specific types.
- [x] T3 `noArrayIndexKey`: domain-based keys.
- [x] T4 a11y: `htmlFor`/`id` on labels, semantic buttons for interactive divs.

Route: delegated direct (one writer; 2+ non-trivial files). TDD: off (no frontend test runner).

## Checks
- `./node_modules/.bin/biome lint frontend/src` (from repo root): in-scope rules at 0.
- `npx tsc --noEmit` (from `frontend/`): exit 0.

## Progress
Writer done (observed):
- `biome lint frontend/src --reporter=summary`: all 7 in-scope rules at 0. Remaining: useExhaustiveDependencies 5, noUnknownAtRules 3, noSvgWithoutTitle 3, useOptionalChain 8, noNonNullAssertion 4, noGlobalIsNan 2, useLiteralKeys 5, useTemplate 2, noUselessFragments 1, useParseIntRadix 1, noUselessCatch 1 (all out of scope).
- `tsc --noEmit` (frontend/): exit 0.
- T1: explicit `type="button"` on all 32 buttons (none were form-submit buttons).
- T2: new `extractErrorMessage` helper in `lib/apiClient.ts` replaces `err: any`; typed raw payloads in ingestion/market/order services; `details: Record<string, unknown>`.
- T3: keys from domain fields (rule_id, ticker+side, field+issue, bar.timestamp, tick.val, line/warning text).
- T4: label htmlFor/id via useId (group labels became span); modal backdrops are sibling `<button aria-label>`; dropzones use overlay button; clickable rows are buttons; PortfolioCard uses stretched overlay button; donut hover handlers moved to pointer events; chart currency group is a fieldset.
- Parent spot check: lint in-scope rules 0 (11 errors / 14 warnings / 10 infos remaining, all out of scope), `tsc --noEmit` exit 0; writer edits normalized with `biome check --write --linter-enabled=false`.
- Commits (both `--no-verify` by user decision: the GGA pre-commit hook reviews whole files against AGENTS.md and rejects on pre-existing violations):
  - `84f6814` style(frontend): format-only snapshot, rebuilt from HEAD via `biome check --write` (verified identical to the user's formatting on all 23 files the writer did not touch).
  - lint-fix commit follows this document.

## Follow-ups (out of scope, reported by GGA review)
- Security: `UserProfileModal` can PATCH `/auth/me` with `role: "ADMIN"`; verify the backend rejects self-role-escalation.
- Hardcoded demo credentials in `AuthModal` client bundle.
- `App.tsx` shows hardcoded fallback metrics (latency, portfolio count, "26 especies activas") as if real.
- `RebalancePanel` executes orders with `|| 1` quantity / `1.0` price fallbacks.
- `services/api.ts` and raw `axios` calls in `App.tsx`/`TopHeader.tsx` bypass `lib/apiClient.ts`.
- Hand-rolled mutations in `PortfolioDetailView` / `RebalancePanel` instead of `useMutation`.
- Remaining Biome rules: useExhaustiveDependencies, noUnknownAtRules, noSvgWithoutTitle, useOptionalChain, noNonNullAssertion, noGlobalIsNan, infos.
- Writer judgment calls to verify visually: donut circles use `role="option"`; drop over "Descartar" in `ExtractDropzone` no longer handled; `AllocationChart` rows are `<button>` wrapping `<div>`s.
