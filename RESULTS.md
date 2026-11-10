# Review results

Reviewed the staged and working-tree changes against the last commit, HEAD `813edb4`, on November 9, 2026. Required ignored frontend source files were also inspected. All five findings below were rechecked against the current files during this review, including direct reproductions where noted.

**Result: changes need fixes before committing.** One high-priority finding (P1) and four normal-priority findings (P2) follow.

## Findings

### [P1] Include required frontend utility modules in version control

Location: `frontend/src/app/page.tsx:3-6`; `.gitignore:17`.

The new frontend imports `@/lib/api`, `@/lib/live`, `@/lib/priceStore`, and `@/lib/types`; components also require `@/lib/format`. The existing unanchored `lib/` ignore rule excludes all five new files under `frontend/src/lib/`. Local typechecking succeeds because these files exist locally, but a normal add/commit omits them, so a fresh checkout cannot build the frontend or Docker image. Confirmed with `git check-ignore -v`. Add an ignore exception and commit the required modules.

### [P2] Persist frozen prices for holdings removed from the watchlist

Location: `backend/app/api/state.py:38-48,67-69`; `backend/app/main.py:26-35`.

Confirmed removal of a held ticker preserves its last price only in the in-memory `frozen` dictionary. After restart this dictionary is empty, and startup subscribes only to watchlisted tickers. An unwatched holding consequently falls back to average cost, changing its reported market value and unrealized P&L; startup records that valuation in portfolio history. A share bought at $100 and frozen at $120 loses $20 of reported value on restart. Persist and restore frozen prices before recording snapshots. Direct state recreation confirmed that the frozen price becomes `None`.

### [P2] Recreate an already-running container after an explicit rebuild

Location: `scripts/start_windows.ps1:21-24`; `scripts/start_mac.sh:29-31`.

When the container is already running, `-Build` / `--build` builds a new image but then enters the already-running branch and leaves the old container serving the old code. A successful rebuild therefore does not apply the requested update. Recreate the container following an explicit build while retaining its named data volume.

### [P2] Handle quantity quantization overflow as a validation error

Location: `backend/app/db/repository.py:99`.

The API accepts the finite positive quantity `1e30`, but `_validate_quantity` calls `quantize` outside its exception handler. This exceeds decimal context precision and raises `decimal.InvalidOperation`, producing an internal error instead of a controlled validation or insufficient-cash response. Directly reproduced by passing the result of `validate_trade('AAPL', 'buy', 1e30)` into `_validate_quantity`. Bound quantities or translate quantization failures into `DbError`.

### [P2] Use Massive previous close for daily-change percentages

Location: `backend/app/api/state.py:50-56`.

`reference_of` uses the first cached price for every market-data source. The project contract (`planning/PLAN.md:178`) requires the previous close for Massive. If a stock closed at $100 and the app starts at $110, the watchlist reports 0% instead of +10%, and restarting resets this baseline again. The existing Massive adapter does not propagate previous close, so carry it through to the new API reference price before presenting the value as daily change.

## Validation and limitations

- Backend: `python -m pytest backend/tests -q -p no:cacheprovider --tb=line` using `backend/.venv/Scripts/python.exe`: **94 passed, 64 setup errors**. All 64 errors were temporary-directory `PermissionError` failures; these do not establish application failures.
- LLM tests run separately: **21 passed**.
- Frontend: `npm run typecheck` **passed**, with locally present ignored modules.
- Frontend: `npm test -- --run` was blocked before tests ran by esbuild `spawn EPERM`.
- Direct Python checks reproduced `InvalidOperation` for quantity `1e30`, and a frozen AAPL price of `120.0` becoming `None` on state recreation with an empty cache.
- Git ignore behavior, startup-script control flow, and the daily-change contract were checked directly.

Inspected API/state/chat/SSE integration, database initialization and trade logic, LLM client and schemas, frontend integration and chart/trade components, Docker configuration, and startup scripts. Production builds, Docker execution, browser E2E, and live provider calls were not run. Some pre-existing review temporary directories could not be enumerated due to access restrictions. No application source fixes were made.

