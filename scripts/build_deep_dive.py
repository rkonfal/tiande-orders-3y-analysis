#!/usr/bin/env python3
import csv
import html
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median


REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = REPO_ROOT / "docs"
SOURCE_ROOT = Path("~/Desktop").expanduser()
SOURCE_FILES = [
    SOURCE_ROOT / "orders_2024_warehouse_order_level.csv",
    SOURCE_ROOT / "orders_2025_warehouse_order_level.csv",
    SOURCE_ROOT / "orders_2026_warehouse_order_level.csv",
]
VALID_STATUS_IDS = {"1", "3", "5"}


@dataclass
class OrderRow:
    order_id: str
    dt: datetime
    raw_customer_id: str
    raw_email: str
    market: str
    status_id: str
    total_czk: float
    items_count: int
    currency: str
    is_counted: bool


def parse_float(value: str) -> float:
    try:
        return float((value or "").strip() or 0.0)
    except ValueError:
        return 0.0


def parse_int(value: str) -> int:
    try:
        return int(float((value or "").strip() or 0))
    except ValueError:
        return 0


def normalize_email(value: str) -> str:
    return (value or "").strip().lower()


def counted_flag(value: str) -> bool:
    return (value or "").strip().lower() in {"t", "true", "1", "yes", "y"}


def market_from_row(row: dict) -> str:
    country = (row.get("delivery_country_code") or row.get("country_code") or "").strip().upper()
    return "SK" if country == "SK" else "CZ"


def fmt_int(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def fmt_money(value: float) -> str:
    return f"{value:,.0f}".replace(",", " ")


def fmt_money2(value: float) -> str:
    return f"{value:,.2f}".replace(",", " ")


def fmt_pct(value: float) -> str:
    return f"{value * 100:.1f} %"


def pct(num: float, den: float) -> float:
    return num / den if den else 0.0


def quantile(values, q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * q
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return ordered[lo]
    weight = pos - lo
    return ordered[lo] * (1 - weight) + ordered[hi] * weight


def write_csv(path: Path, rows, fieldnames):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def load_orders():
    orders = []
    email_to_ids = defaultdict(set)
    for path in SOURCE_FILES:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                raw_customer_id = (row.get("customer_id") or "").strip()
                raw_email = normalize_email(row.get("customer_email") or "")
                if raw_customer_id and raw_email:
                    email_to_ids[raw_email].add(raw_customer_id)
                orders.append(
                    OrderRow(
                        order_id=(row.get("order_id") or "").strip(),
                        dt=datetime.fromisoformat(row["order_created_at_prague"]),
                        raw_customer_id=raw_customer_id,
                        raw_email=raw_email,
                        market=market_from_row(row),
                        status_id=(row.get("status_id") or "").strip(),
                        total_czk=parse_float(row.get("order_total_czk") or ""),
                        items_count=parse_int(row.get("items_count") or ""),
                        currency=(row.get("currency") or "").strip().upper(),
                        is_counted=counted_flag(row.get("is_counted") or ""),
                    )
                )
    orders.sort(key=lambda row: (row.dt, row.order_id))
    customer_keys = {}
    for order in orders:
        if order.raw_customer_id:
            customer_keys[order.order_id] = f"id:{order.raw_customer_id}"
        elif order.raw_email and len(email_to_ids[order.raw_email]) == 1:
            customer_keys[order.order_id] = f"id:{next(iter(email_to_ids[order.raw_email]))}"
        elif order.raw_email:
            customer_keys[order.order_id] = f"email:{order.raw_email}"
        else:
            customer_keys[order.order_id] = ""
    return orders, customer_keys


def build():
    orders, customer_keys = load_orders()
    latest_dt = max(order.dt for order in orders)
    latest_date = latest_dt.date()
    valid_orders = [o for o in orders if o.is_counted and o.status_id in VALID_STATUS_IDS and o.total_czk > 0]
    identified_valid = [o for o in valid_orders if customer_keys[o.order_id]]

    customers = defaultdict(list)
    for order in identified_valid:
        customers[customer_keys[order.order_id]].append(order)

    # core per-customer stats
    customer_stats = {}
    order_band_rows = []
    value_revenues = []
    all_gaps = []
    first_to_second_by_market = {"CZ": {"eligible": 0, "conv90": 0}, "SK": {"eligible": 0, "conv90": 0}}
    for customer_key, customer_orders in customers.items():
        customer_orders.sort(key=lambda row: (row.dt, row.order_id))
        revenue = sum(o.total_czk for o in customer_orders)
        order_count = len(customer_orders)
        avg_order = revenue / order_count
        items_avg = sum(o.items_count for o in customer_orders) / order_count
        last_dt = customer_orders[-1].dt
        recency_days = (latest_date - last_dt.date()).days
        gaps = [(customer_orders[i].dt - customer_orders[i - 1].dt).days for i in range(1, order_count)]
        all_gaps.extend(gaps)
        if customer_orders[0].dt <= latest_dt - timedelta(days=90):
            market = customer_orders[0].market
            first_to_second_by_market[market]["eligible"] += 1
            if order_count >= 2 and (customer_orders[1].dt - customer_orders[0].dt).days <= 90:
                first_to_second_by_market[market]["conv90"] += 1
        customer_stats[customer_key] = {
            "orders": order_count,
            "revenue_czk": revenue,
            "aov_czk": avg_order,
            "avg_items": items_avg,
            "first_dt": customer_orders[0].dt,
            "last_dt": last_dt,
            "recency_days": recency_days,
            "market": customer_orders[0].market,
            "first_order_revenue_czk": customer_orders[0].total_czk,
        }
        value_revenues.append(revenue)
        band = "1" if order_count == 1 else "2" if order_count == 2 else "3" if order_count == 3 else "4-5" if order_count <= 5 else "6+"
        order_band_rows.append({"customer": customer_key, "band": band, "revenue_czk": revenue})

    # value concentration
    ranked_customers = sorted(
        [{"customer": k, "revenue_czk": v["revenue_czk"], "orders": v["orders"]} for k, v in customer_stats.items()],
        key=lambda row: row["revenue_czk"],
        reverse=True,
    )
    total_identified_revenue = sum(row["revenue_czk"] for row in ranked_customers)
    concentration_rows = []
    for bucket in (0.01, 0.05, 0.10):
        n = max(1, int(len(ranked_customers) * bucket))
        share = pct(sum(row["revenue_czk"] for row in ranked_customers[:n]), total_identified_revenue)
        concentration_rows.append(
            {"bucket": f"top_{int(bucket*100)}pct", "customers": n, "revenue_share": round(share, 4)}
        )

    band_summary = defaultdict(lambda: {"band": "", "customers": 0, "revenue_czk": 0.0})
    for row in order_band_rows:
        target = band_summary[row["band"]]
        target["band"] = row["band"]
        target["customers"] += 1
        target["revenue_czk"] += row["revenue_czk"]
    value_tier_rows = []
    for band in ["1", "2", "3", "4-5", "6+"]:
        row = band_summary[band]
        value_tier_rows.append(
            {
                "band": band,
                "customers": row["customers"],
                "revenue_czk": round(row["revenue_czk"], 2),
                "revenue_share": round(pct(row["revenue_czk"], total_identified_revenue), 4),
            }
        )

    # cohorts
    cohorts = defaultdict(list)
    for key, stats in customer_stats.items():
        cohorts[stats["first_dt"].strftime("%Y-%m")].append((key, stats))

    cohort_rows = []
    cohort_heatmap_rows = []
    for cohort, members in sorted(cohorts.items()):
        first_dt = min(stats["first_dt"] for _, stats in members)
        size = len(members)
        first_rev = sum(stats["first_order_revenue_czk"] for _, stats in members)
        row = {
            "cohort": cohort,
            "customers": size,
            "first_order_revenue_czk": round(first_rev, 2),
            "rate_30d": "",
            "rate_60d": "",
            "rate_90d": "",
            "rate_180d": "",
            "rate_365d": "",
            "third_order_90d": "",
        }
        heat = {"cohort": cohort}
        for window in (30, 60, 90, 180, 365):
            if first_dt > latest_dt - timedelta(days=window):
                row[f"rate_{window}d"] = None
                heat[f"rate_{window}d"] = None
                continue
            eligible = size
            converted = 0
            for key, stats in members:
                customer_orders = customers[key]
                if len(customer_orders) >= 2 and (customer_orders[1].dt - customer_orders[0].dt).days <= window:
                    converted += 1
            rate = round(pct(converted, eligible), 4)
            row[f"rate_{window}d"] = rate
            heat[f"rate_{window}d"] = rate
        if first_dt <= latest_dt - timedelta(days=90):
            converted = 0
            eligible = 0
            for key, stats in members:
                customer_orders = customers[key]
                if len(customer_orders) >= 2 and customer_orders[1].dt <= latest_dt - timedelta(days=90):
                    eligible += 1
                    if len(customer_orders) >= 3 and (customer_orders[2].dt - customer_orders[1].dt).days <= 90:
                        converted += 1
            row["third_order_90d"] = round(pct(converted, eligible), 4) if eligible else None
        else:
            row["third_order_90d"] = None
        cohort_rows.append(row)
        cohort_heatmap_rows.append(heat)

    # driver decomposition ytd 2026 vs 2025 same cutoff
    h1_2026_end = latest_dt
    h1_2025_end = latest_dt.replace(year=2025)

    def period_orders(start: datetime, end: datetime, market: str = ""):
        subset = [o for o in identified_valid if start <= o.dt <= end and (not market or o.market == market)]
        active_customers = {customer_keys[o.order_id] for o in subset}
        return {
            "orders": len(subset),
            "revenue_czk": round(sum(o.total_czk for o in subset), 2),
            "active_customers": len(active_customers),
            "orders_per_customer": round(pct(len(subset), len(active_customers)), 4),
            "aov_czk": round(pct(sum(o.total_czk for o in subset), len(subset)), 2),
        }

    driver_rows = []
    overall_2025 = period_orders(datetime(2025, 1, 1), h1_2025_end)
    overall_2026 = period_orders(datetime(2026, 1, 1), h1_2026_end)
    for market in ["ALL", "CZ", "SK"]:
        p25 = overall_2025 if market == "ALL" else period_orders(datetime(2025, 1, 1), h1_2025_end, market)
        p26 = overall_2026 if market == "ALL" else period_orders(datetime(2026, 1, 1), h1_2026_end, market)
        driver_rows.append(
            {
                "market": market,
                "active_customers_2025": p25["active_customers"],
                "active_customers_2026": p26["active_customers"],
                "active_customers_delta": round(pct(p26["active_customers"] - p25["active_customers"], p25["active_customers"]), 4),
                "orders_per_customer_2025": p25["orders_per_customer"],
                "orders_per_customer_2026": p26["orders_per_customer"],
                "orders_per_customer_delta": round(pct(p26["orders_per_customer"] - p25["orders_per_customer"], p25["orders_per_customer"]), 4),
                "aov_2025": p25["aov_czk"],
                "aov_2026": p26["aov_czk"],
                "aov_delta": round(pct(p26["aov_czk"] - p25["aov_czk"], p25["aov_czk"]), 4),
                "revenue_2025": p25["revenue_czk"],
                "revenue_2026": p26["revenue_czk"],
                "revenue_delta": round(pct(p26["revenue_czk"] - p25["revenue_czk"], p25["revenue_czk"]), 4),
            }
        )

    # monthly/market bridge with YoY
    monthly_market = defaultdict(lambda: {"month": "", "market": "", "orders": 0, "revenue_czk": 0.0, "customers": set()})
    for o in identified_valid:
        key = (o.dt.strftime("%Y-%m"), o.market)
        monthly_market[key]["month"] = key[0]
        monthly_market[key]["market"] = key[1]
        monthly_market[key]["orders"] += 1
        monthly_market[key]["revenue_czk"] += o.total_czk
        monthly_market[key]["customers"].add(customer_keys[o.order_id])
    bridge_rows = []
    for (month, market), row in sorted(monthly_market.items()):
        customers_count = len(row["customers"])
        yoy_month = f"{int(month[:4]) - 1}{month[4:]}"
        base = monthly_market.get((yoy_month, market))
        rev_yoy = None
        ord_yoy = None
        cust_yoy = None
        if base:
            rev_yoy = round(pct(row["revenue_czk"] - base["revenue_czk"], base["revenue_czk"]), 4) if base["revenue_czk"] else None
            ord_yoy = round(pct(row["orders"] - base["orders"], base["orders"]), 4) if base["orders"] else None
            cust_yoy = round(pct(customers_count - len(base["customers"]), len(base["customers"])), 4) if base["customers"] else None
        bridge_rows.append(
            {
                "month": month,
                "market": market,
                "orders": row["orders"],
                "revenue_czk": round(row["revenue_czk"], 2),
                "customers": customers_count,
                "aov_czk": round(pct(row["revenue_czk"], row["orders"]), 2),
                "orders_per_customer": round(pct(row["orders"], customers_count), 4),
                "revenue_yoy": rev_yoy,
                "orders_yoy": ord_yoy,
                "customers_yoy": cust_yoy,
            }
        )

    # opportunity sizing segments
    revenue_p90 = quantile(value_revenues, 0.9)
    aov_p90 = quantile([s["aov_czk"] for s in customer_stats.values()], 0.9)

    segment_defs = []
    for key, stats in customer_stats.items():
        if stats["orders"] == 1 and stats["recency_days"] > 90:
            segment_defs.append(("1x_91d_plus", key, stats))
        if stats["orders"] == 1 and 46 <= stats["recency_days"] <= 90:
            segment_defs.append(("1x_46_90d", key, stats))
        if 2 <= stats["orders"] <= 4 and 46 <= stats["recency_days"] <= 90:
            segment_defs.append(("repeat_2_4_lapse_46_90d", key, stats))
        if stats["revenue_czk"] >= revenue_p90 and stats["recency_days"] > 60:
            segment_defs.append(("vip_dormant", key, stats))
        if stats["aov_czk"] >= aov_p90 and stats["orders"] <= 3 and stats["recency_days"] <= 180:
            segment_defs.append(("high_aov_low_frequency", key, stats))

    seg_aggs = defaultdict(lambda: {"segment": "", "customers": 0, "revenue_czk": 0.0, "aov_total": 0.0, "recency_total": 0})
    for seg, key, stats in segment_defs:
        agg = seg_aggs[seg]
        agg["segment"] = seg
        agg["customers"] += 1
        agg["revenue_czk"] += stats["revenue_czk"]
        agg["aov_total"] += stats["aov_czk"]
        agg["recency_total"] += stats["recency_days"]
    opportunity_rows = []
    uplift_rules = {
        "1x_91d_plus": 0.10,
        "1x_46_90d": 0.15,
        "repeat_2_4_lapse_46_90d": 0.12,
        "vip_dormant": 0.10,
        "high_aov_low_frequency": 0.15,
    }
    priority_rules = {
        "1x_91d_plus": "P1",
        "1x_46_90d": "P1",
        "repeat_2_4_lapse_46_90d": "P1",
        "vip_dormant": "P1",
        "high_aov_low_frequency": "P2",
    }
    for seg in ["1x_91d_plus", "1x_46_90d", "repeat_2_4_lapse_46_90d", "vip_dormant", "high_aov_low_frequency"]:
        agg = seg_aggs[seg]
        avg_aov = pct(agg["aov_total"], agg["customers"])
        revenue_potential = agg["customers"] * uplift_rules[seg] * avg_aov
        opportunity_rows.append(
            {
                "segment": seg,
                "customers": agg["customers"],
                "segment_revenue_czk": round(agg["revenue_czk"], 2),
                "avg_aov_czk": round(avg_aov, 2),
                "avg_recency_days": round(pct(agg["recency_total"], agg["customers"]), 1) if agg["customers"] else 0,
                "expected_conversion": uplift_rules[seg],
                "estimated_incremental_revenue_czk": round(revenue_potential, 2),
                "priority": priority_rules[seg],
            }
        )

    # market diagnostics
    market_diag = {}
    for market in ["CZ", "SK"]:
        market_orders = [o for o in identified_valid if o.market == market]
        market_customers = [stats for stats in customer_stats.values() if stats["market"] == market]
        market_diag[market] = {
            "customers": len(market_customers),
            "revenue_czk": round(sum(o.total_czk for o in market_orders), 2),
            "orders": len(market_orders),
            "aov_czk": round(pct(sum(o.total_czk for o in market_orders), len(market_orders)), 2),
            "avg_items_per_order": round(pct(sum(o.items_count for o in market_orders), len(market_orders)), 2),
            "median_customer_ltv": round(median([s["revenue_czk"] for s in market_customers]), 2) if market_customers else 0,
            "first_to_second_90d": round(
                pct(first_to_second_by_market[market]["conv90"], first_to_second_by_market[market]["eligible"]), 4
            ),
            "seen_before_order_share": round(
                pct(
                    sum(max(0, len(customers[k]) - 1) for k, s in customer_stats.items() if s["market"] == market),
                    len(market_orders),
                ),
                4,
            ),
        }

    # RFM matrix
    def recency_bucket(days: int) -> str:
        if days <= 45:
            return "0-45d"
        if days <= 90:
            return "46-90d"
        if days <= 180:
            return "91-180d"
        return "181d+"

    def frequency_bucket(orders_count: int) -> str:
        if orders_count == 1:
            return "1"
        if orders_count <= 4:
            return "2-4"
        return "5+"

    rfm = defaultdict(lambda: {"recency_bucket": "", "frequency_bucket": "", "customers": 0, "revenue_czk": 0.0})
    for stats in customer_stats.values():
        rb = recency_bucket(stats["recency_days"])
        fb = frequency_bucket(stats["orders"])
        target = rfm[(rb, fb)]
        target["recency_bucket"] = rb
        target["frequency_bucket"] = fb
        target["customers"] += 1
        target["revenue_czk"] += stats["revenue_czk"]
    rfm_rows = []
    for rb in ["0-45d", "46-90d", "91-180d", "181d+"]:
        for fb in ["1", "2-4", "5+"]:
            row = rfm[(rb, fb)]
            rfm_rows.append(
                {
                    "recency_bucket": rb,
                    "frequency_bucket": fb,
                    "customers": row["customers"],
                    "revenue_czk": round(row["revenue_czk"], 2),
                    "revenue_share": round(pct(row["revenue_czk"], total_identified_revenue), 4),
                }
            )

    # data quality impact
    quality_impact = []
    for flag in ["orders_up_to_1_czk", "zero_value_orders", "cz_orders_with_eur_currency", "sk_orders_with_czk_currency", "error_status_orders"]:
        if flag == "orders_up_to_1_czk":
            subset = [o for o in orders if 0 < o.total_czk <= 1]
        elif flag == "zero_value_orders":
            subset = [o for o in orders if o.total_czk == 0]
        elif flag == "cz_orders_with_eur_currency":
            subset = [o for o in orders if o.market == "CZ" and o.currency == "EUR"]
        elif flag == "sk_orders_with_czk_currency":
            subset = [o for o in orders if o.market == "SK" and o.currency == "CZK"]
        else:
            subset = [o for o in orders if o.status_id == "8"]
        quality_impact.append(
            {
                "flag": flag,
                "orders": len(subset),
                "revenue_czk": round(sum(o.total_czk for o in subset), 2),
                "revenue_share_of_topline": round(pct(sum(o.total_czk for o in subset), sum(o.total_czk for o in valid_orders)), 4),
            }
        )

    # scenario model
    baseline_first90 = next(row["rate_90d"] for row in cohort_rows if row["cohort"] == "2026-03") if any(r["cohort"] == "2026-03" for r in cohort_rows) else 0.30
    scenario_rows = [
        {"scenario": "Base", "first_to_second_90d": 0.43, "reactivation_1x_91d": 0.10, "cz_aov_uplift": 0.03},
        {"scenario": "Upside", "first_to_second_90d": 0.48, "reactivation_1x_91d": 0.15, "cz_aov_uplift": 0.06},
        {"scenario": "Downside", "first_to_second_90d": 0.40, "reactivation_1x_91d": 0.07, "cz_aov_uplift": 0.00},
    ]
    avg_first_order_aov = pct(sum(s["first_order_revenue_czk"] for s in customer_stats.values()), len(customer_stats))
    cz_aov = market_diag["CZ"]["aov_czk"]
    for row in scenario_rows:
        extra_second_order_revenue = max(0.0, row["first_to_second_90d"] - 0.4267) * 15203 * avg_first_order_aov
        extra_reactivation_revenue = row["reactivation_1x_91d"] * 14284 * avg_first_order_aov
        extra_cz_aov_revenue = row["cz_aov_uplift"] * market_diag["CZ"]["orders"] * cz_aov
        row["estimated_incremental_revenue_czk"] = round(extra_second_order_revenue + extra_reactivation_revenue + extra_cz_aov_revenue, 2)

    # export csvs
    write_csv(DOCS_DIR / "cohort_retention.csv", cohort_rows, list(cohort_rows[0].keys()))
    write_csv(DOCS_DIR / "driver_decomposition.csv", driver_rows, list(driver_rows[0].keys()))
    write_csv(DOCS_DIR / "segment_opportunities.csv", opportunity_rows, list(opportunity_rows[0].keys()))
    write_csv(DOCS_DIR / "value_concentration.csv", concentration_rows, list(concentration_rows[0].keys()))
    write_csv(DOCS_DIR / "customer_value_tiers.csv", value_tier_rows, list(value_tier_rows[0].keys()))
    write_csv(DOCS_DIR / "market_month_bridge.csv", bridge_rows, list(bridge_rows[0].keys()))
    write_csv(DOCS_DIR / "rfm_matrix.csv", rfm_rows, list(rfm_rows[0].keys()))
    write_csv(DOCS_DIR / "data_quality_impact.csv", quality_impact, list(quality_impact[0].keys()))
    write_csv(DOCS_DIR / "scenario_model.csv", scenario_rows, list(scenario_rows[0].keys()))

    # html helpers
    def table(rows, columns, headers=None):
        headers = headers or columns
        thead = "".join(f"<th>{html.escape(headers.get(col, col))}</th>" for col in columns)
        body_rows = []
        for row in rows:
            cells = []
            for col in columns:
                val = row.get(col)
                if val is None:
                    cells.append("<td>—</td>")
                elif isinstance(val, float) and col.endswith("_pct"):
                    cells.append(f"<td>{fmt_pct(val)}</td>")
                else:
                    cells.append(f"<td>{html.escape(str(val))}</td>")
            body_rows.append("<tr>" + "".join(cells) + "</tr>")
        return f"<table><thead><tr>{thead}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"

    cohort_display = []
    for row in cohort_rows:
        cohort_display.append(
            {
                "cohort": row["cohort"],
                "customers": fmt_int(row["customers"]),
                "first_order_revenue_czk": f"{fmt_money(row['first_order_revenue_czk'])} Kč",
                "rate_30d": fmt_pct(row["rate_30d"]) if row["rate_30d"] is not None else "—",
                "rate_60d": fmt_pct(row["rate_60d"]) if row["rate_60d"] is not None else "—",
                "rate_90d": fmt_pct(row["rate_90d"]) if row["rate_90d"] is not None else "—",
                "rate_180d": fmt_pct(row["rate_180d"]) if row["rate_180d"] is not None else "—",
                "third_order_90d": fmt_pct(row["third_order_90d"]) if row["third_order_90d"] is not None else "—",
            }
        )
    driver_display = []
    for row in driver_rows:
        driver_display.append(
            {
                "market": row["market"],
                "active_customers_2025": fmt_int(row["active_customers_2025"]),
                "active_customers_2026": fmt_int(row["active_customers_2026"]),
                "active_customers_delta": fmt_pct(row["active_customers_delta"]),
                "orders_per_customer_2025": f"{row['orders_per_customer_2025']:.2f}",
                "orders_per_customer_2026": f"{row['orders_per_customer_2026']:.2f}",
                "orders_per_customer_delta": fmt_pct(row["orders_per_customer_delta"]),
                "aov_2025": f"{fmt_money2(row['aov_2025'])} Kč",
                "aov_2026": f"{fmt_money2(row['aov_2026'])} Kč",
                "aov_delta": fmt_pct(row["aov_delta"]),
                "revenue_2025": f"{fmt_money(row['revenue_2025'])} Kč",
                "revenue_2026": f"{fmt_money(row['revenue_2026'])} Kč",
                "revenue_delta": fmt_pct(row["revenue_delta"]),
            }
        )
    opp_display = []
    for row in opportunity_rows:
        opp_display.append(
            {
                "segment": row["segment"],
                "customers": fmt_int(row["customers"]),
                "segment_revenue_czk": f"{fmt_money(row['segment_revenue_czk'])} Kč",
                "avg_aov_czk": f"{fmt_money2(row['avg_aov_czk'])} Kč",
                "avg_recency_days": row["avg_recency_days"],
                "expected_conversion": fmt_pct(row["expected_conversion"]),
                "estimated_incremental_revenue_czk": f"{fmt_money(row['estimated_incremental_revenue_czk'])} Kč",
                "priority": row["priority"],
            }
        )
    conc_display = [
        {
            "bucket": row["bucket"].replace("_", " "),
            "customers": fmt_int(row["customers"]),
            "revenue_share": fmt_pct(row["revenue_share"]),
        }
        for row in concentration_rows
    ]
    tier_display = [
        {
            "band": row["band"],
            "customers": fmt_int(row["customers"]),
            "revenue_czk": f"{fmt_money(row['revenue_czk'])} Kč",
            "revenue_share": fmt_pct(row["revenue_share"]),
        }
        for row in value_tier_rows
    ]
    market_display = []
    for market in ["CZ", "SK"]:
        row = market_diag[market]
        market_display.append(
            {
                "market": market,
                "customers": fmt_int(row["customers"]),
                "revenue_czk": f"{fmt_money(row['revenue_czk'])} Kč",
                "orders": fmt_int(row["orders"]),
                "aov_czk": f"{fmt_money2(row['aov_czk'])} Kč",
                "avg_items_per_order": f"{row['avg_items_per_order']:.2f}",
                "median_customer_ltv": f"{fmt_money2(row['median_customer_ltv'])} Kč",
                "first_to_second_90d": fmt_pct(row["first_to_second_90d"]),
                "seen_before_order_share": fmt_pct(row["seen_before_order_share"]),
            }
        )
    scenario_display = [
        {
            "scenario": row["scenario"],
            "first_to_second_90d": fmt_pct(row["first_to_second_90d"]),
            "reactivation_1x_91d": fmt_pct(row["reactivation_1x_91d"]),
            "cz_aov_uplift": fmt_pct(row["cz_aov_uplift"]),
            "estimated_incremental_revenue_czk": f"{fmt_money(row['estimated_incremental_revenue_czk'])} Kč",
        }
        for row in scenario_rows
    ]
    rfm_display = [
        {
            "recency_bucket": row["recency_bucket"],
            "frequency_bucket": row["frequency_bucket"],
            "customers": fmt_int(row["customers"]),
            "revenue_czk": f"{fmt_money(row['revenue_czk'])} Kč",
            "revenue_share": fmt_pct(row["revenue_share"]),
        }
        for row in rfm_rows
    ]
    quality_display = [
        {
            "flag": row["flag"],
            "orders": fmt_int(row["orders"]),
            "revenue_czk": f"{fmt_money(row['revenue_czk'])} Kč",
            "revenue_share_of_topline": fmt_pct(row["revenue_share_of_topline"]),
        }
        for row in quality_impact
    ]
    yoy_focus = [row for row in bridge_rows if row["month"].startswith("2026-") and row["month"] <= "2026-06"]
    yoy_focus_display = [
        {
            "month": row["month"],
            "market": row["market"],
            "customers": fmt_int(row["customers"]),
            "orders": fmt_int(row["orders"]),
            "revenue_czk": f"{fmt_money(row['revenue_czk'])} Kč",
            "aov_czk": f"{fmt_money2(row['aov_czk'])} Kč",
            "revenue_yoy": fmt_pct(row["revenue_yoy"]) if row["revenue_yoy"] is not None else "—",
            "orders_yoy": fmt_pct(row["orders_yoy"]) if row["orders_yoy"] is not None else "—",
        }
        for row in yoy_focus
    ]

    html_page = f"""<!doctype html>
<html lang="cs">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Plná analýza objednávek | TianDe 2024-2026</title>
  <style>
    :root {{
      --bg: #f4efe7;
      --surface: #fffdf8;
      --line: #e7dccb;
      --ink: #201814;
      --muted: #6d6259;
      --accent: #9a3412;
      --accent2: #0f766e;
      --soft: #f6e7d2;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background:
        radial-gradient(circle at top left, rgba(154, 52, 18, 0.10), transparent 28%),
        radial-gradient(circle at top right, rgba(15, 118, 110, 0.10), transparent 24%),
        var(--bg);
      color: var(--ink);
      font-family: Georgia, "Iowan Old Style", "Palatino Linotype", serif;
    }}
    .wrap {{ max-width: 1240px; margin: 0 auto; padding: 28px; }}
    .hero, .panel, .card {{
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 24px;
      box-shadow: 0 10px 34px rgba(32, 24, 20, 0.05);
    }}
    .hero {{ padding: 28px; }}
    .panel {{ padding: 22px; margin-top: 18px; }}
    .cards {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:14px; margin-top:18px; }}
    .card {{ padding: 18px; }}
    .kicker {{ font-size:12px; letter-spacing:.08em; text-transform:uppercase; color:var(--muted); margin-bottom:8px; }}
    .value {{ font-size:30px; font-weight:700; }}
    .lede {{ font-size:18px; line-height:1.6; max-width:980px; }}
    .meta {{ color:var(--muted); font-size:14px; line-height:1.6; margin-bottom:10px; }}
    h1 {{ margin:0 0 10px; font-size:42px; line-height:1.05; }}
    h2 {{ margin:0 0 14px; font-size:24px; }}
    .grid-2 {{ display:grid; grid-template-columns:1.2fr 1fr; gap:18px; margin-top:18px; }}
    .grid-3 {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:18px; margin-top:18px; }}
    ul {{ margin:0; padding-left:20px; line-height:1.7; }}
    table {{ width:100%; border-collapse:collapse; font-size:14px; }}
    th, td {{ padding:10px 8px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; }}
    th {{ font-size:12px; text-transform:uppercase; letter-spacing:.06em; color:var(--muted); }}
    .pill {{ display:inline-block; padding:6px 10px; border-radius:999px; background:var(--soft); color:var(--accent); font-size:13px; margin:0 8px 8px 0; }}
    .cta {{ display:inline-block; padding:10px 14px; border-radius:999px; background:var(--accent); color:#fff; text-decoration:none; font-size:14px; margin-top:12px; }}
    .note {{ color:var(--muted); font-size:13px; line-height:1.6; }}
    a {{ color:var(--accent); text-decoration:none; }}
    @media (max-width: 980px) {{
      .cards, .grid-2, .grid-3 {{ grid-template-columns:1fr; }}
      h1 {{ font-size:34px; }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <section class="hero">
      <div class="meta">Plná analýza | Pokrytí: {orders[0].dt.strftime('%d.%m.%Y %H:%M')} až {latest_dt.strftime('%d.%m.%Y %H:%M')} | Exporty: 2024 + 2025 + H1 2026 | Aktualizováno: {datetime.now().strftime('%d.%m.%Y %H:%M')}</div>
      <h1>TianDe 2024-2026: co se děje, proč se to děje a co s tím</h1>
      <div class="lede">Tahle verze je už celá pohromadě. Ne jen krátké shrnutí. Je tu rozklad propadu roku 2026, návratnost zákazníků podle měsíců prvního nákupu, kde leží peníze, proč je Slovensko silnější než Česko a hlavně co udělat hned.</div>
      <div style="margin-top:14px;">
        <span class="pill">Kde mizí obrat</span>
        <span class="pill">Kdo se vrací a kdo ne</span>
        <span class="pill">Kde leží nejrychlejší peníze</span>
        <span class="pill">Česko vs Slovensko</span>
        <span class="pill">Co udělat hned</span>
      </div>
      <a class="cta" href="./ceo-one-pager.html">CEO one-pager</a>
      <a class="cta" href="https://github.com/rkonfal/tiande-orders-3y-analysis" style="margin-left:8px; background:var(--accent2);">GitHub repo</a>
    </section>

    <section class="cards">
      <div class="card"><div class="kicker">Platné tržby</div><div class="value">{fmt_money(sum(o.total_czk for o in valid_orders))} Kč</div></div>
      <div class="card"><div class="kicker">Platné objednávky</div><div class="value">{fmt_int(len(valid_orders))}</div></div>
      <div class="card"><div class="kicker">Podíl tržeb od vracejících se zákazníků</div><div class="value">{fmt_pct(pct(sum(v['revenue_czk'] for v in customer_stats.values() if v['orders'] >= 2), total_identified_revenue))}</div></div>
      <div class="card"><div class="kicker">Typická mezera mezi objednávkami</div><div class="value">{median(all_gaps) if all_gaps else 0} dní</div></div>
    </section>

    <section class="grid-2">
      <div class="panel">
        <h2>Co ta čísla opravdu říkají</h2>
        <ul>
          <li>`Rok 2026` je proti stejnému období roku `2025` opravdu slabší. Není to dojem, ale reálný pokles objednávek i tržeb.</li>
          <li>Byznys stojí hlavně na vracejících se zákaznících. Zákazníci s `6 a více` objednávkami nesou `{fmt_pct(next(r['revenue_share'] for r in value_tier_rows if r['band']=='6+'))}` identifikovaných tržeb.</li>
          <li>`Nejlepších 10 %` zákazníků dělá `{fmt_pct(next(r['revenue_share'] for r in concentration_rows if r['bucket']=='top_10pct'))}` tržeb. O tuto skupinu se musí pečovat zvlášť.</li>
          <li>Typická mezera mezi objednávkami je `{median(all_gaps) if all_gaps else 0}` dní, horní čtvrtina je kolem `{sorted(all_gaps)[int((len(all_gaps)-1)*0.75)] if all_gaps else 0}` dní a horní desetina kolem `{sorted(all_gaps)[int((len(all_gaps)-1)*0.9)] if all_gaps else 0}` dní. Nejcitlivější okno pro návrat je tedy zhruba `30 až 90 dní`.</li>
        </ul>
      </div>
      <div class="panel">
        <h2>Co tady teď nově je</h2>
        <ul>
          <li>rozklad propadu roku 2026 na počet aktivních zákazníků, četnost nákupů a průměrnou objednávku</li>
          <li>návratnost zákazníků podle měsíce prvního nákupu místo jednoho souhrnného čísla</li>
          <li>přehled segmentů v penězích: kde leží největší rychlá příležitost</li>
          <li>závislost obratu na malé skupině nejlepších zákazníků</li>
          <li>podrobnější srovnání Česka a Slovenska</li>
        </ul>
      </div>
    </section>

    <section class="panel">
      <h2>Co udělat hned</h2>
      <table>
        <thead>
          <tr><th>Krok</th><th>Proč</th><th>Co přesně udělat</th><th>Co hlídat</th></tr>
        </thead>
        <tbody>
          <tr><td>1. Dotlačit druhý nákup</td><td>Tady leží nejrychlejší růst bez další akvizice</td><td>Spustit e-mail a SMS na zákazníky 0–45 dní po prvním nákupu. Nabídnout doplnění rutiny, ne plošnou slevu.</td><td>Podíl zákazníků, kteří udělají 2. objednávku do 30 / 60 / 90 dní</td></tr>
          <tr><td>2. Vrátit staré jednorázové zákazníky</td><td>Skupina `1x 91+ dní` je největší zásoba rychlých peněz</td><td>Udělát návratovou kampaň na bestsellery a jednoduché sety. Netlačit široký katalog, ale jasnou volbu.</td><td>Návratovost skupiny `1x 91+ dní`</td></tr>
          <tr><td>3. Zvednout košík v Česku</td><td>Česko dělá objem, ale vydělá méně na objednávku než Slovensko</td><td>Nasadit sety, dárek od určité částky a chytřejší nabídku v košíku.</td><td>Průměrná hodnota objednávky v Česku</td></tr>
          <tr><td>4. Chránit nejlepší zákazníky</td><td>Malá skupina lidí dělá velkou část obratu</td><td>Pro nejlepší zákazníky dát přednostní nabídky, dárky a dřívější přístup, ne obyčejnou slevovou akci.</td><td>Počet aktivních nejlepších zákazníků a jejich obrat</td></tr>
          <tr><td>5. Oddělit Česko a Slovensko</td><td>Slovensko se chová jinak a objednávka tam vychází lépe</td><td>Vést samostatné kampaně, samostatné texty a samostatné nabídky.</td><td>Rozdíl Česko vs Slovensko v průměrné objednávce a návratovosti</td></tr>
        </tbody>
      </table>
    </section>

    <section class="grid-2">
      <div class="panel">
        <h2>Jak to celé uchopit</h2>
        <ul>
          <li>Nebrat to jako jeden report, ale jako čtyři samostatné úkoly: návrat po 1. nákupu, zrychlení dalších nákupů, zvýšení českého košíku a péče o nejlepší zákazníky.</li>
          <li>Nedělat všechno naráz. Začít tím, co vrací peníze nejrychleji: druhý nákup, staré jednorázové zákazníky a český košík.</li>
          <li>Každou část řídit zvlášť. Jinou nabídku dostane člověk po první objednávce, jinou dostane dlouho neaktivní zákazník a jinou nejlepší zákazník.</li>
          <li>Česko a Slovensko neřídit jedním textem a jednou nabídkou. Každý trh potřebuje vlastní přístup.</li>
          <li>Nehodnotit to podle pocitu, ale podle několika čísel, která se budou sledovat pořád dokola.</li>
        </ul>
      </div>
      <div class="panel">
        <h2>Jak s tím pracovat každý týden</h2>
        <table>
          <thead>
            <tr><th>Rytmus</th><th>Co přesně udělat</th></tr>
          </thead>
          <tbody>
            <tr><td>1x týdně</td><td>Projít druhý nákup do 30 / 60 / 90 dní, návrat jednorázových zákazníků, český košík a počet aktivních nejlepších zákazníků.</td></tr>
            <tr><td>1x za 14 dní</td><td>Vyhodnotit, která nabídka funguje lépe: set, dárek od určité částky, doprava zdarma nebo návrat přes bestseller.</td></tr>
            <tr><td>1x měsíčně</td><td>Porovnat Česko a Slovensko, které skupiny sílí a které slábnou, a podle toho upravit kampaně i nabídku na e-shopu.</td></tr>
            <tr><td>1x za čtvrtletí</td><td>Rozhodnout, jestli se víc vyplatí tlačit návrat zákazníků, nebo už znovu přidat víc peněz do získávání nových lidí.</td></tr>
          </tbody>
        </table>
      </div>
    </section>

    <section class="panel">
      <h2>1. Proč je rok 2026 slabší</h2>
      <div class="note">Tržby se tady rozpadají na tři hlavní části: počet aktivních zákazníků, kolikrát nakoupí a jak velkou mají objednávku. Srovnání je ve stejném časovém okně `1. 1. – 29. 6. 15:44` v `2025` a `2026`.</div>
      {table(driver_display, ["market","active_customers_2025","active_customers_2026","active_customers_delta","orders_per_customer_2025","orders_per_customer_2026","orders_per_customer_delta","aov_2025","aov_2026","aov_delta","revenue_2025","revenue_2026","revenue_delta"], {
        "market":"Market",
        "active_customers_2025":"Active cust. 2025",
        "active_customers_2026":"Active cust. 2026",
        "active_customers_delta":"Cust. delta",
        "orders_per_customer_2025":"Orders/cust. 2025",
        "orders_per_customer_2026":"Orders/cust. 2026",
        "orders_per_customer_delta":"Freq. delta",
        "aov_2025":"AOV 2025",
        "aov_2026":"AOV 2026",
        "aov_delta":"AOV delta",
        "revenue_2025":"Revenue 2025",
        "revenue_2026":"Revenue 2026",
        "revenue_delta":"Revenue delta"
      })}
      <div class="note" style="margin-top:10px;">Jednoduše řečeno: když ubývá aktivních zákazníků a zároveň se nezrychluje další nákup, nestačí přikoupit reklamu. Je potřeba řešit kvalitu nových zákazníků i návrat těch stávajících.</div>
    </section>

    <section class="panel">
      <h2>2. Jak se vracejí zákazníci podle měsíce prvního nákupu</h2>
      <div class="note">Každý řádek je měsíc prvního nákupu. Tohle ukazuje, jestli novější skupiny zákazníků jsou lepší, nebo horší než dřív.</div>
      {table(cohort_display, ["cohort","customers","first_order_revenue_czk","rate_30d","rate_60d","rate_90d","rate_180d","third_order_90d"], {
        "cohort":"Cohort",
        "customers":"Customers",
        "first_order_revenue_czk":"1st order revenue",
        "rate_30d":"2nd <=30d",
        "rate_60d":"2nd <=60d",
        "rate_90d":"2nd <=90d",
        "rate_180d":"2nd <=180d",
        "third_order_90d":"3rd <=90d from 2nd"
      })}
      <div class="note" style="margin-top:10px;">Praktický závěr: sleduj hlavně nové měsíce. Pokud se zhoršuje druhý nákup do `90 dní`, je problém už v kvalitě prvního nákupu nebo v prvních navazujících kampaních.</div>
    </section>

    <section class="grid-2">
      <div class="panel">
        <h2>3. Kde leží nejrychlejší peníze</h2>
        {table(opp_display, ["segment","customers","segment_revenue_czk","avg_aov_czk","avg_recency_days","expected_conversion","estimated_incremental_revenue_czk","priority"], {
          "segment":"Segment",
          "customers":"Customers",
          "segment_revenue_czk":"Segment revenue",
          "avg_aov_czk":"Avg AOV",
          "avg_recency_days":"Avg recency",
          "expected_conversion":"Model conv.",
          "estimated_incremental_revenue_czk":"Est. uplift",
          "priority":"Priority"
        })}
        <div class="note" style="margin-top:10px;">Tohle není účetní předpověď. Je to praktický odhad, který ukazuje, kde má práce nejrychlejší návrat.</div>
      </div>
      <div class="panel">
        <h2>Co z toho plyne</h2>
        <ul>
          <li>`1x_91d_plus` je největší a nejlevnější skupina pro návrat. Už `10 %` návratnost při dnešní průměrné objednávce znamená asi `{fmt_money(next(r['estimated_incremental_revenue_czk'] for r in opportunity_rows if r['segment']=='1x_91d_plus'))} Kč` navíc.</li>
          <li>`repeat_2_4_lapse_46_90d` je menší skupina, ale kvalitnější. Hodí se pro rychlé návratové kampaně.</li>
          <li>`vip_dormant` a `high_aov_low_frequency` jsou malé, ale hodnotné skupiny. Tady netlačit slevu, ale důvod vrátit se.</li>
        </ul>
      </div>
    </section>

    <section class="grid-2">
      <div class="panel">
        <h2>4. Jak moc obrat stojí na malé skupině lidí</h2>
        {table(conc_display, ["bucket","customers","revenue_share"], {
          "bucket":"Bucket",
          "customers":"Customers",
          "revenue_share":"Revenue share"
        })}
        <div class="note" style="margin-top:10px;">Nejlepších `1 %` zákazníků dělá `{fmt_pct(next(r['revenue_share'] for r in concentration_rows if r['bucket']=='top_1pct'))}` obratu. To je velká páka, ale i riziko. Když tahle skupina oslabí, pocítí to celý byznys.</div>
      </div>
      <div class="panel">
        <h2>Kolik vydělávají zákazníci podle počtu objednávek</h2>
        {table(tier_display, ["band","customers","revenue_czk","revenue_share"], {
          "band":"Orders/customer",
          "customers":"Customers",
          "revenue_czk":"Revenue",
          "revenue_share":"Revenue share"
        })}
      </div>
    </section>

    <section class="panel">
      <h2>5. Česko vs Slovensko</h2>
      {table(market_display, ["market","customers","revenue_czk","orders","aov_czk","avg_items_per_order","median_customer_ltv","first_to_second_90d","seen_before_order_share"], {
        "market":"Market",
        "customers":"Customers",
        "revenue_czk":"Revenue",
        "orders":"Orders",
        "aov_czk":"AOV",
        "avg_items_per_order":"Avg items/order",
        "median_customer_ltv":"Median LTV",
        "first_to_second_90d":"1→2 <=90d",
        "seen_before_order_share":"Seen-before share"
      })}
      <div class="note" style="margin-top:10px;">Slovensko není silnější náhodou. Má vyšší průměrnou objednávku a podobnou rychlost návratu. Česko proto nepotřebuje jen víc objednávek, ale hlavně vyšší hodnotu košíku.</div>
    </section>

    <section class="panel">
      <h2>6. Vývoj po měsících</h2>
      {table(yoy_focus_display, ["month","market","customers","orders","revenue_czk","aov_czk","orders_yoy","revenue_yoy"], {
        "month":"Month",
        "market":"Market",
        "customers":"Customers",
        "orders":"Orders",
        "revenue_czk":"Revenue",
        "aov_czk":"AOV",
        "orders_yoy":"Orders YoY",
        "revenue_yoy":"Revenue YoY"
      })}
    </section>

    <section class="grid-2">
      <div class="panel">
        <h2>7. Přehled zákazníků podle čerstvosti a počtu nákupů</h2>
        {table(rfm_display, ["recency_bucket","frequency_bucket","customers","revenue_czk","revenue_share"], {
          "recency_bucket":"Recency",
          "frequency_bucket":"Frequency",
          "customers":"Customers",
          "revenue_czk":"Revenue",
          "revenue_share":"Revenue share"
        })}
      </div>
      <div class="panel">
        <h2>8. Datové odchylky a jejich dopad</h2>
        {table(quality_display, ["flag","orders","revenue_czk","revenue_share_of_topline"], {
          "flag":"Flag",
          "orders":"Orders",
          "revenue_czk":"Revenue",
          "revenue_share_of_topline":"Share of topline"
        })}
        <div class="note" style="margin-top:10px;">Důležité: `první viděná objednávka` neznamená nutně první objednávku v životě zákazníka. Znamená jen první objednávku v datech, která máme za roky 2024–2026. Rok 2024 je proto potřeba číst opatrně.</div>
      </div>
    </section>

    <section class="panel">
      <h2>9. Co může ještě letos zvednout výsledek</h2>
      {table(scenario_display, ["scenario","first_to_second_90d","reactivation_1x_91d","cz_aov_uplift","estimated_incremental_revenue_czk"], {
        "scenario":"Scenario",
        "first_to_second_90d":"1→2 <=90d",
        "reactivation_1x_91d":"1x 91+d react.",
        "cz_aov_uplift":"CZ AOV uplift",
        "estimated_incremental_revenue_czk":"Est. incremental revenue"
      })}
      <div class="note" style="margin-top:10px;">Smysl této tabulky je jednoduchý: ukázat, že i bez velkého tlaku na novou akvizici se dá část výkonu vrátit lepší prací s návratem zákazníků a s hodnotou objednávky.</div>
    </section>

    <section class="panel">
      <h2>10. Kdo má co udělat</h2>
      <table>
        <thead>
          <tr><th>Krok</th><th>Proč</th><th>Dopad</th><th>Náročnost</th><th>Kdo</th><th>Metrika</th></tr>
        </thead>
        <tbody>
          <tr><td>Kampaň na druhý nákup pro zákazníky 0–45 dní po prvním nákupu</td><td>nejrychlejší cesta k vyšším tržbám ze stávající báze</td><td>Vysoký</td><td>Střední</td><td>CRM / e-shop</td><td>2. objednávka do 30 / 60 / 90 dní</td></tr>
          <tr><td>Návratová kampaň pro skupinu 1x 91+ dní</td><td>největší skupina, kde leží rychlé peníze</td><td>Vysoký</td><td>Nízká</td><td>CRM</td><td>návratovost 1x 91+ dní</td></tr>
          <tr><td>Sety a dárek od určité částky v Česku</td><td>zvednutí průměrné objednávky v největším trhu</td><td>Vysoký</td><td>Střední</td><td>E-shop / obchod</td><td>průměrná objednávka v Česku</td></tr>
          <tr><td>Zvláštní péče o nejlepší zákazníky</td><td>ochrana nejhodnotnější části obratu</td><td>Střední až vysoký</td><td>Střední</td><td>CRM</td><td>udržení a obrat nejlepších zákazníků</td></tr>
          <tr><td>Oddělit komunikaci pro Česko a Slovensko</td><td>Slovensko má jinou ekonomiku objednávky</td><td>Střední</td><td>Nízká</td><td>CRM / reklama</td><td>rozdíl mezi Českem a Slovenskem</td></tr>
        </tbody>
      </table>
    </section>

    <section class="panel">
      <h2>Downloads</h2>
      <ul>
        <li><a href="./cohort_retention.csv">cohort_retention.csv</a></li>
        <li><a href="./driver_decomposition.csv">driver_decomposition.csv</a></li>
        <li><a href="./segment_opportunities.csv">segment_opportunities.csv</a></li>
        <li><a href="./value_concentration.csv">value_concentration.csv</a></li>
        <li><a href="./customer_value_tiers.csv">customer_value_tiers.csv</a></li>
        <li><a href="./market_month_bridge.csv">market_month_bridge.csv</a></li>
        <li><a href="./rfm_matrix.csv">rfm_matrix.csv</a></li>
        <li><a href="./scenario_model.csv">scenario_model.csv</a></li>
      </ul>
    </section>
  </div>
</body>
</html>
"""
    (DOCS_DIR / "deep-dive.html").write_text(html_page, encoding="utf-8")
    (DOCS_DIR / "index.html").write_text(html_page, encoding="utf-8")


if __name__ == "__main__":
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    build()
