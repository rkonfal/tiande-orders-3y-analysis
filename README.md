# TianDe orders 3Y analysis

This repo contains an aggregated deep-dive over TianDe warehouse order exports for:

- 2024-01-01 to 2024-12-31
- 2025-01-01 to 2025-12-31
- 2026-01-01 to 2026-06-29 15:44

## Scope

- `399 364` raw rows across three yearly CSV exports
- valid topline = `status_id in {1,3,5}`, `order_total_czk > 0`, `is_counted = true`
- customer behavior subset = identifiable orders via `customer_id`, fallback normalized email, plus unambiguous email-to-id stitching
- note: `new` / `repeat` style fields in generated exports mean `first seen in the 2024-2026 window` vs `seen earlier in the same window`, not guaranteed first-ever vs repeat-ever

## Core findings

- Customers with 2+ observed orders drive the business: 71.2 % of identified customers generated 88.6 % of identified revenue.
- The largest observed opportunity is the base with a single observed order: 15,203 customers.
- Observed speed to 2nd order within 90 days is 42.7 %; observed speed to 3rd order within 90 days from the 2nd is 52.7 %. 
- SK monetizes materially better than CZ on AOV: 1 863.31 CZK vs 1 558.47 CZK.
- YTD to the same final timestamp window as 2026 vs 2025: orders -16.9 %, revenue -9.8 %.

## Files

- `scripts/build_analysis.py` regenerates all outputs from local source CSVs
- `docs/index.html` is the live report for GitHub Pages
- `docs/*.csv` and `docs/summary.json` contain aggregated exports

## Privacy

Raw order files stay local and are intentionally excluded from git.
