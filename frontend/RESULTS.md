# Review results

Reviewed uncommitted tracked and untracked application changes against HEAD `813edb4` on November 9, 2026. Independently rechecked the existing findings against the current source and reran the validation listed below. Changes need fixes before committing.

## Findings

### [P1] Include the frontend utility modules in version control

Location: `frontend/src/app/page.tsx:3-6`; `.gitignore:17`.

The new frontend imports `@/lib/api`, `live`, `priceStore`, and `types`; components also require `format`. The existing unanchored `lib/` ignore rule excludes all five new files in `frontend/src/lib/`. Local typechecking passes because the files exist locally, but a normal add/commit omits them, leaving fresh checkouts unable to build the frontend or Docker image. Add an ignore exception and commit these modules. Confirmed with `git check-ignore -v` for all five files.

### [P2] Persist frozen prices for holdings removed from the watchlist

Locations: `backend/app/api/state.py:38-48,67-69`; `backend/app/main.py:26-35`.

Removing a held ticker with confirmation preserves its last price only in the in-memory `frozen` dictionary. After restart, only watchlisted tickers are subscribed and this dictionary is empty. The unwatched holding falls back to average cost, changing its reported value and unrealized P&L; startup records that valuation in portfolio history. For a share bought at $100 and frozen at $120, restart removes $20 of reported value without a trade. Persist and restore frozen prices before valuation and snapshots. Direct state recreation confirmed that a frozen $120 price becomes unavailable after restart (`120` before recreation, `None` afterward).

### [P2] Recreate running containers after an explicit rebuild

Locations: `scripts/start_windows.ps1:21-24`; `scripts/start_mac.sh:29-31`.

If FinAlly is running, `-Build` or `--build` creates a new image but the subsequent running-container branch skips recreation. Users continue seeing the old application despite explicitly rebuilding. Recreate the container after a successful requested build, retaining the data volume. Confirmed by inspecting both scripts' control flow; Docker was not executed.

### [P2] Handle quantity quantization overflow as a validation error

Location: `backend/app/db/repository.py:99`.

The API accepts the finite positive quantity `1e30`, but the repository calls Decimal `quantize` outside its exception handler. This exceeds the decimal context precision and raises `InvalidOperation`, producing an internal error rather than a controlled validation or insufficient-cash response. Bound quantities or catch quantization failures and raise `DbError`. Directly reproduced `validate_trade` accepting `1e30` and `_validate_quantity` raising `InvalidOperation`.

### [P2] Use Massive's previous close for daily change

Location: `backend/app/api/state.py:50-56`.

The new `reference_of` helper uses the first cached price for every data source. The contract in `planning/PLAN.md:178` requires Massive's previous close. A stock that closed at $100 and starts streaming at $110 therefore displays 0% daily change instead of +10%, and restarting changes the baseline. Propagate previous close from the Massive snapshot into the cache and use it for this source. The existing adapter currently discards this value, so integration work is required.

## Validation and limits

- `npm run typecheck`: passed with the locally present ignored utility modules.
- `npm test -- --run`: blocked before test execution by esbuild `spawn EPERM` while loading Vitest configuration.
- Direct Python checks confirmed quantity overflow and loss of frozen prices when application state is recreated.
- Git ignore checks confirmed all five frontend utility modules are excluded.
- Reviewed API/state/chat/stream integration, repository trade handling, frontend state, LLM client, Docker configuration, and startup scripts. Backend test suites, production builds, Docker execution, browser E2E, and live provider calls were not run in this review.
- No application source fixes were made.

The repository root is `C:/Users/jchav/projects/finally`, outside this session's permitted write area. This report is saved in the writable workspace root, `frontend/RESULTS.md`; the existing repository-root report was not modified.

