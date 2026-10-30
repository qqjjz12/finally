# Review results

Reviewed all tracked changes against HEAD and new marketplace/plugin files. Application source code is unchanged. Found two actionable integration issues.

## [P2] Align the revised SSE contract with the existing producer

**Location:** `planning/PLAN.md:185-189` (also line 178)

The revised contract tells frontend consumers to read one ticker per message, with an ISO timestamp and `reference_price`. However, `backend/app/market/stream.py` sends all prices in a dictionary keyed by ticker. `PriceUpdate.to_dict()` in `backend/app/market/models.py` emits Unix seconds and has no `reference_price`; its percentage change measures movement since the previous update. A frontend built against this specification will read missing top-level fields and cannot calculate the promised daily change. Update the producer, model, and cache, or explicitly identify these changes as prerequisites for frontend integration rather than describing the market-data component as complete.

## [P2] Preserve a valuation price when removing a held ticker

**Location:** `planning/PLAN.md:177`

The new behavior promises that a removed ticker's open position remains valued at its last cached price. Both existing data sources delete that cache entry in `remove_ticker()`, as required by `backend/app/market/interface.py`; `PriceCache.get_price()` then returns `None`. The proposed positions schema has no retained market-price field either. Implementing watchlist removal through the existing interface therefore loses the value required for the heatmap, positions table, and portfolio total. Specify a separate retained valuation-price store, including restart behavior and the corresponding interface changes, or keep held tickers tracked until their positions close.

## Validation and scope

- All five changed/new JSON configuration files parse successfully.
- Inspected the marketplace manifest, plugin manifest, and both hook definitions. Did not execute the Stop hook because it launches another review.
- `git diff --check` reports an extra blank line at the end of `.claude/settings.json`; this is formatting only.
- No application tests run because application source code is unchanged. Findings were checked against the existing stream, model, cache, interface, and both data-source implementations.
- `RESULTS.md` is the requested review output and was excluded from findings.
