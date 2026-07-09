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


def svg_bar_chart(points, width=920, height=320, pad_x=56, pad_y=24, label_step=1):
    if not points:
        return "<svg viewBox='0 0 920 320'></svg>"
    values = [point["value"] for point in points]
    max_value = max(values) or 1
    plot_w = width - pad_x * 2
    plot_h = height - pad_y * 2
    bar_w = plot_w / max(1, len(points))
    y_ticks = []
    for i in range(5):
        ratio = i / 4
        val = max_value - ratio * max_value
        y = pad_y + plot_h * ratio
        y_ticks.append(
            f"<g><line x1='{pad_x}' y1='{y:.2f}' x2='{width - pad_x}' y2='{y:.2f}' stroke='#e2e8f0'/>"
            f"<text x='8' y='{y + 4:.2f}' font-size='12' fill='#64748b'>{html.escape(fmt_money(val))}</text></g>"
        )
    bars = []
    for idx, point in enumerate(points):
        x = pad_x + idx * bar_w + 2
        h = (point["value"] / max_value) * plot_h if max_value else 0
        y = pad_y + plot_h - h
        color = point.get("color") or "#9a3412"
        bars.append(
            f"<rect x='{x:.2f}' y='{y:.2f}' width='{max(2, bar_w - 4):.2f}' height='{h:.2f}' rx='3' fill='{color}'></rect>"
        )
        if idx % label_step == 0:
            bars.append(
                f"<text x='{x + (bar_w - 4) / 2:.2f}' y='{height - 6}' text-anchor='middle' font-size='11' fill='#64748b'>{html.escape(point['label'])}</text>"
            )
    return (
        f"<svg viewBox='0 0 {width} {height}' role='img' aria-label='chart'>"
        f"{''.join(y_ticks)}"
        f"{''.join(bars)}"
        f"<line x1='{pad_x}' y1='{height - pad_y}' x2='{width - pad_x}' y2='{height - pad_y}' stroke='#cbd5e1'/>"
        "</svg>"
    )


def svg_grouped_bar_chart(groups, series, width=920, height=340, pad_x=56, pad_y=24):
    if not groups or not series:
        return "<svg viewBox='0 0 920 340'></svg>"
    values = [group.get(key, 0) for group in groups for key, _, _ in series]
    max_value = max(values) or 1
    plot_w = width - pad_x * 2
    plot_h = height - pad_y * 2
    group_w = plot_w / max(1, len(groups))
    inner_gap = 4
    bar_w = max(8, (group_w - inner_gap * (len(series) + 1)) / max(1, len(series)))
    y_ticks = []
    for i in range(5):
        ratio = i / 4
        val = max_value - ratio * max_value
        y = pad_y + plot_h * ratio
        y_ticks.append(
            f"<g><line x1='{pad_x}' y1='{y:.2f}' x2='{width - pad_x}' y2='{y:.2f}' stroke='#e2e8f0'/>"
            f"<text x='8' y='{y + 4:.2f}' font-size='12' fill='#64748b'>{html.escape(fmt_money(val))}</text></g>"
        )
    bars = []
    for idx, group in enumerate(groups):
        base_x = pad_x + idx * group_w
        for s_idx, (key, _, color) in enumerate(series):
            value = group.get(key, 0)
            h = (value / max_value) * plot_h if max_value else 0
            x = base_x + inner_gap + s_idx * (bar_w + inner_gap)
            y = pad_y + plot_h - h
            bars.append(
                f"<rect x='{x:.2f}' y='{y:.2f}' width='{bar_w:.2f}' height='{h:.2f}' rx='3' fill='{color}'></rect>"
            )
        bars.append(
            f"<text x='{base_x + group_w / 2:.2f}' y='{height - 6}' text-anchor='middle' font-size='11' fill='#64748b'>{html.escape(group['label'])}</text>"
        )
    legend = []
    legend_x = pad_x
    for _, label, color in series:
        legend.append(
            f"<rect x='{legend_x}' y='6' width='12' height='12' rx='2' fill='{color}'></rect>"
            f"<text x='{legend_x + 18}' y='16' font-size='12' fill='#64748b'>{html.escape(label)}</text>"
        )
        legend_x += max(120, len(label) * 7 + 28)
    return (
        f"<svg viewBox='0 0 {width} {height}' role='img' aria-label='chart'>"
        f"{''.join(y_ticks)}{''.join(bars)}{''.join(legend)}"
        f"<line x1='{pad_x}' y1='{height - pad_y}' x2='{width - pad_x}' y2='{height - pad_y}' stroke='#cbd5e1'/>"
        "</svg>"
    )


def svg_horizontal_bar_chart(points, width=920, height=320, pad_x=180, pad_y=24):
    if not points:
        return "<svg viewBox='0 0 920 320'></svg>"
    values = [point["value"] for point in points]
    max_value = max(values) or 1
    plot_w = width - pad_x - 24
    row_h = (height - pad_y * 2) / max(1, len(points))
    parts = []
    for idx, point in enumerate(points):
        y = pad_y + idx * row_h + 4
        w = (point["value"] / max_value) * plot_w if max_value else 0
        color = point.get("color") or "#9a3412"
        parts.append(
            f"<text x='8' y='{y + row_h / 2 + 4:.2f}' font-size='12' fill='#334155'>{html.escape(point['label'])}</text>"
            f"<rect x='{pad_x}' y='{y:.2f}' width='{w:.2f}' height='{max(10, row_h - 10):.2f}' rx='4' fill='{color}'></rect>"
            f"<text x='{pad_x + w + 8:.2f}' y='{y + row_h / 2 + 4:.2f}' font-size='12' fill='#64748b'>{html.escape(point.get('value_label', fmt_money(point['value'])))}</text>"
        )
    return f"<svg viewBox='0 0 {width} {height}' role='img' aria-label='chart'>{''.join(parts)}</svg>"


def svg_line_chart(points, width=920, height=320, pad_x=56, pad_y=24, color="#9a3412", fill="#f6e7d2"):
    if not points:
        return "<svg viewBox='0 0 920 320'></svg>"
    values = [point["value"] for point in points]
    max_value = max(values) or 1
    min_value = min(values)
    span = max_value - min_value or 1
    plot_w = width - pad_x * 2
    plot_h = height - pad_y * 2
    coords = []
    for idx, point in enumerate(points):
        x = pad_x + plot_w * idx / max(1, len(points) - 1)
        y = pad_y + plot_h - ((point["value"] - min_value) / span) * plot_h
        coords.append((x, y))
    polyline = " ".join(f"{x:.2f},{y:.2f}" for x, y in coords)
    area = f"{pad_x},{height - pad_y} " + polyline + f" {coords[-1][0]:.2f},{height - pad_y}"
    ticks = []
    for i in range(5):
        ratio = i / 4
        val = max_value - ratio * span
        y = pad_y + plot_h * ratio
        ticks.append(
            f"<g><line x1='{pad_x}' y1='{y:.2f}' x2='{width - pad_x}' y2='{y:.2f}' stroke='#e2e8f0'/>"
            f"<text x='8' y='{y + 4:.2f}' font-size='12' fill='#64748b'>{html.escape(fmt_money(val))}</text></g>"
        )
    labels = []
    step = max(1, math.ceil(len(points) / 8))
    for idx, point in enumerate(points):
        if idx % step == 0:
            labels.append(
                f"<text x='{coords[idx][0]:.2f}' y='{height - 6}' text-anchor='middle' font-size='11' fill='#64748b'>{html.escape(point['label'])}</text>"
            )
    dots = "".join(f"<circle cx='{x:.2f}' cy='{y:.2f}' r='4' fill='{color}'></circle>" for x, y in coords)
    return (
        f"<svg viewBox='0 0 {width} {height}' role='img' aria-label='chart'>"
        f"{''.join(ticks)}<polygon points='{area}' fill='{fill}' opacity='0.9'></polygon>"
        f"<polyline points='{polyline}' fill='none' stroke='{color}' stroke-width='3'></polyline>{dots}{''.join(labels)}</svg>"
    )


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

    yearly_rollup = defaultdict(lambda: {"year": "", "revenue_czk": 0.0, "orders": 0, "customers": set()})
    monthly_rollup = defaultdict(lambda: {"month": "", "revenue_czk": 0.0, "orders": 0, "customers": set()})
    for order in valid_orders:
        year = order.dt.strftime("%Y")
        month = order.dt.strftime("%Y-%m")
        yearly_rollup[year]["year"] = year
        yearly_rollup[year]["revenue_czk"] += order.total_czk
        yearly_rollup[year]["orders"] += 1
        monthly_rollup[month]["month"] = month
        monthly_rollup[month]["revenue_czk"] += order.total_czk
        monthly_rollup[month]["orders"] += 1
        customer_key = customer_keys.get(order.order_id, "")
        if customer_key:
            yearly_rollup[year]["customers"].add(customer_key)
            monthly_rollup[month]["customers"].add(customer_key)

    yearly_rows = []
    prev_year = None
    for year in sorted(yearly_rollup):
        row = yearly_rollup[year]
        customers_count = len(row["customers"])
        current = {
            "year": year,
            "revenue_czk": round(row["revenue_czk"], 2),
            "orders": row["orders"],
            "customers": customers_count,
            "aov_czk": round(pct(row["revenue_czk"], row["orders"]), 2),
            "revenue_yoy": None,
            "orders_yoy": None,
            "customers_yoy": None,
        }
        if prev_year:
            current["revenue_yoy"] = round(pct(current["revenue_czk"] - prev_year["revenue_czk"], prev_year["revenue_czk"]), 4)
            current["orders_yoy"] = round(pct(current["orders"] - prev_year["orders"], prev_year["orders"]), 4)
            current["customers_yoy"] = round(pct(current["customers"] - prev_year["customers"], prev_year["customers"]), 4)
        yearly_rows.append(current)
        prev_year = current

    monthly_30_rows = []
    month_points = []
    for month in sorted(monthly_rollup)[:30]:
        row = monthly_rollup[month]
        month_type = "Běžný"
        color = "#c08457"
        if month.endswith("-11"):
            month_type = "Black Friday"
            color = "#9a3412"
        elif month.endswith("-12"):
            month_type = "Prosinec"
            color = "#0f766e"
        monthly_30_rows.append(
            {
                "month": month,
                "month_type": month_type,
                "revenue_czk": round(row["revenue_czk"], 2),
                "orders": row["orders"],
                "customers": len(row["customers"]),
                "aov_czk": round(pct(row["revenue_czk"], row["orders"]), 2),
            }
        )
        month_points.append({"label": month[2:], "value": row["revenue_czk"], "color": color})

    bf_pattern_rows = []
    for year in ["2024", "2025"]:
        regular = [row["revenue_czk"] for row in monthly_30_rows if row["month"].startswith(year) and row["month_type"] == "Běžný"]
        nov = next((row["revenue_czk"] for row in monthly_30_rows if row["month"] == f"{year}-11"), None)
        dec = next((row["revenue_czk"] for row in monthly_30_rows if row["month"] == f"{year}-12"), None)
        if not regular or nov is None or dec is None:
            continue
        avg_regular = sum(regular) / len(regular)
        bf_pattern_rows.append(
            {
                "year": year,
                "regular_avg_revenue_czk": round(avg_regular, 2),
                "november_delta": round(pct(nov - avg_regular, avg_regular), 4),
                "december_delta": round(pct(dec - avg_regular, avg_regular), 4),
            }
        )

    pdf_band_summary = defaultdict(lambda: {"band": "", "customers": 0, "revenue_czk": 0.0})
    for stats in customer_stats.values():
        if stats["orders"] == 1:
            band = "1"
        elif stats["orders"] <= 5:
            band = "2-5"
        elif stats["orders"] <= 12:
            band = "6-12"
        else:
            band = "13+"
        target = pdf_band_summary[band]
        target["band"] = band
        target["customers"] += 1
        target["revenue_czk"] += stats["revenue_czk"]
    pdf_segment_rows = []
    for band in ["1", "2-5", "6-12", "13+"]:
        row = pdf_band_summary[band]
        pdf_segment_rows.append(
            {
                "band": band,
                "customers": row["customers"],
                "revenue_czk": round(row["revenue_czk"], 2),
                "revenue_share": round(pct(row["revenue_czk"], total_identified_revenue), 4),
            }
        )

    core_customers = [stats for stats in customer_stats.values() if stats["orders"] >= 13]
    observed_years = max(1.0, (latest_dt - orders[0].dt).days / 365.25)
    core_activity_rows = [
        {
            "segment": "13+ objednávek",
            "customers": len(core_customers),
            "active_90d_share": round(pct(sum(1 for stats in core_customers if stats["recency_days"] <= 90), len(core_customers)), 4) if core_customers else 0.0,
            "dormant_share": round(pct(sum(1 for stats in core_customers if stats["recency_days"] > 90), len(core_customers)), 4) if core_customers else 0.0,
            "avg_annual_spend_czk": round(pct(sum(stats["revenue_czk"] for stats in core_customers), len(core_customers)) / observed_years, 2) if core_customers else 0.0,
        }
    ]

    quarterly_rollup = defaultdict(lambda: {"quarter": "", "new_customers": 0, "eligible_90": 0, "returned_90": 0})
    for customer_key, stats in customer_stats.items():
        quarter = f"{stats['first_dt'].year}-Q{((stats['first_dt'].month - 1) // 3) + 1}"
        quarterly_rollup[quarter]["quarter"] = quarter
        quarterly_rollup[quarter]["new_customers"] += 1
        if stats["first_dt"] <= latest_dt - timedelta(days=90):
            quarterly_rollup[quarter]["eligible_90"] += 1
            customer_orders = customers[customer_key]
            if len(customer_orders) >= 2 and (customer_orders[1].dt - customer_orders[0].dt).days <= 90:
                quarterly_rollup[quarter]["returned_90"] += 1
    quarterly_rows = []
    for quarter in sorted(quarterly_rollup):
        row = quarterly_rollup[quarter]
        quarterly_rows.append(
            {
                "quarter": quarter,
                "new_customers": row["new_customers"],
                "return_90d": round(pct(row["returned_90"], row["eligible_90"]), 4) if row["eligible_90"] else None,
            }
        )

    eligible_for_return = 0
    returned_gaps = []
    window_counts = {"do_30": 0, "31_90": 0, "90_plus": 0, "bez_navratu_do_90": 0}
    for customer_key, stats in customer_stats.items():
        if stats["first_dt"] > latest_dt - timedelta(days=90):
            continue
        eligible_for_return += 1
        customer_orders = customers[customer_key]
        if len(customer_orders) < 2:
            window_counts["bez_navratu_do_90"] += 1
            continue
        gap = (customer_orders[1].dt - customer_orders[0].dt).days
        returned_gaps.append(gap)
        if gap <= 30:
            window_counts["do_30"] += 1
        elif gap <= 90:
            window_counts["31_90"] += 1
        else:
            window_counts["90_plus"] += 1
            window_counts["bez_navratu_do_90"] += 1
    second_purchase_rows = []
    for label, key in [
        ("do 30 dní", "do_30"),
        ("31–90 dní", "31_90"),
        ("90+ dní", "90_plus"),
        ("bez návratu do 90 dní", "bez_navratu_do_90"),
    ]:
        second_purchase_rows.append(
            {
                "window": label,
                "customers": window_counts[key],
                "share": round(pct(window_counts[key], eligible_for_return), 4) if eligible_for_return else 0.0,
            }
        )
    second_purchase_median = median(returned_gaps) if returned_gaps else 0

    free_shipping_threshold = 1600
    under_threshold_orders = [order for order in valid_orders if order.total_czk < free_shipping_threshold]
    under_threshold_gaps = [free_shipping_threshold - order.total_czk for order in under_threshold_orders]
    free_shipping_rows = [
        {
            "metric": "Objednávky pod 1 600 Kč",
            "value": len(under_threshold_orders),
            "share": round(pct(len(under_threshold_orders), len(valid_orders)), 4),
        },
        {
            "metric": "Mediánová mezera do 1 600 Kč",
            "value": round(median(under_threshold_gaps), 2) if under_threshold_gaps else 0.0,
            "share": None,
        },
        {
            "metric": "Objednávky v pásmu 1 400–1 600 Kč",
            "value": sum(1 for order in valid_orders if 1400 <= order.total_czk < 1600),
            "share": round(pct(sum(1 for order in valid_orders if 1400 <= order.total_czk < 1600), len(valid_orders)), 4),
        },
    ]

    progression_rollup = defaultdict(lambda: {"purchase_label": "", "orders": 0, "revenue_czk": 0.0, "items_count": 0})
    for customer_orders in customers.values():
        for idx, order in enumerate(customer_orders, start=1):
            if idx <= 10:
                label = str(idx)
            elif idx <= 15:
                label = "11-15"
            elif idx <= 19:
                label = "16-19"
            else:
                label = "20+"
            target = progression_rollup[label]
            target["purchase_label"] = label
            target["orders"] += 1
            target["revenue_czk"] += order.total_czk
            target["items_count"] += order.items_count
    purchase_progression_rows = []
    for label in [str(i) for i in range(1, 11)] + ["11-15", "16-19", "20+"]:
        row = progression_rollup[label]
        purchase_progression_rows.append(
            {
                "purchase_label": label,
                "orders": row["orders"],
                "aov_czk": round(pct(row["revenue_czk"], row["orders"]), 2) if row["orders"] else 0.0,
                "avg_items": round(pct(row["items_count"], row["orders"]), 2) if row["orders"] else 0.0,
            }
        )

    weekday_names = ["Pondělí", "Úterý", "Středa", "Čtvrtek", "Pátek", "Sobota", "Neděle"]
    weekday_counts = [0] * 7
    hour_counts = [0] * 24
    for order in valid_orders:
        weekday_counts[order.dt.weekday()] += 1
        hour_counts[order.dt.hour] += 1
    weekday_rows = []
    for idx, name in enumerate(weekday_names):
        weekday_rows.append(
            {
                "weekday": name,
                "orders": weekday_counts[idx],
                "share": round(pct(weekday_counts[idx], len(valid_orders)), 4),
            }
        )
    hourly_rows = []
    for hour in range(24):
        hourly_rows.append(
            {
                "hour": f"{hour:02d}:00",
                "orders": hour_counts[hour],
                "share": round(pct(hour_counts[hour], len(valid_orders)), 4),
            }
        )
    strongest_weekday = max(weekday_rows, key=lambda row: row["orders"])
    weakest_weekday = min(weekday_rows, key=lambda row: row["orders"])
    peak_hour = max(hourly_rows, key=lambda row: row["orders"])
    evening_share = round(pct(sum(hour_counts[hour] for hour in [18, 19, 20, 21]), len(valid_orders)), 4)

    write_csv(DOCS_DIR / "yearly_metrics.csv", yearly_rows, list(yearly_rows[0].keys()))
    write_csv(DOCS_DIR / "monthly_metrics.csv", monthly_30_rows, list(monthly_30_rows[0].keys()))
    write_csv(DOCS_DIR / "bf_pattern.csv", bf_pattern_rows, list(bf_pattern_rows[0].keys()))
    write_csv(DOCS_DIR / "customer_segment_structure.csv", pdf_segment_rows, list(pdf_segment_rows[0].keys()))
    write_csv(DOCS_DIR / "core_customer_network.csv", core_activity_rows, list(core_activity_rows[0].keys()))
    write_csv(DOCS_DIR / "quarterly_acquisition_retention.csv", quarterly_rows, list(quarterly_rows[0].keys()))
    write_csv(DOCS_DIR / "second_purchase_windows.csv", second_purchase_rows, list(second_purchase_rows[0].keys()))
    write_csv(DOCS_DIR / "free_shipping_gap.csv", free_shipping_rows, list(free_shipping_rows[0].keys()))
    write_csv(DOCS_DIR / "purchase_progression.csv", purchase_progression_rows, list(purchase_progression_rows[0].keys()))
    write_csv(DOCS_DIR / "weekday_behavior.csv", weekday_rows, list(weekday_rows[0].keys()))
    write_csv(DOCS_DIR / "hourly_behavior.csv", hourly_rows, list(hourly_rows[0].keys()))

    yearly_display = [
        {
            "year": row["year"],
            "revenue_czk": f"{fmt_money(row['revenue_czk'])} Kč",
            "orders": fmt_int(row["orders"]),
            "customers": fmt_int(row["customers"]),
            "aov_czk": f"{fmt_money2(row['aov_czk'])} Kč",
            "revenue_yoy": fmt_pct(row["revenue_yoy"]) if row["revenue_yoy"] is not None else "—",
            "orders_yoy": fmt_pct(row["orders_yoy"]) if row["orders_yoy"] is not None else "—",
            "customers_yoy": fmt_pct(row["customers_yoy"]) if row["customers_yoy"] is not None else "—",
        }
        for row in yearly_rows
    ]
    monthly_30_display = [
        {
            "month": row["month"],
            "month_type": row["month_type"],
            "revenue_czk": f"{fmt_money(row['revenue_czk'])} Kč",
            "orders": fmt_int(row["orders"]),
            "customers": fmt_int(row["customers"]),
            "aov_czk": f"{fmt_money2(row['aov_czk'])} Kč",
        }
        for row in monthly_30_rows
    ]
    bf_pattern_display = [
        {
            "year": row["year"],
            "regular_avg_revenue_czk": f"{fmt_money(row['regular_avg_revenue_czk'])} Kč",
            "november_delta": fmt_pct(row["november_delta"]),
            "december_delta": fmt_pct(row["december_delta"]),
        }
        for row in bf_pattern_rows
    ]
    pdf_segment_display = [
        {
            "band": row["band"],
            "customers": fmt_int(row["customers"]),
            "revenue_czk": f"{fmt_money(row['revenue_czk'])} Kč",
            "revenue_share": fmt_pct(row["revenue_share"]),
        }
        for row in pdf_segment_rows
    ]
    core_activity_display = [
        {
            "segment": row["segment"],
            "customers": fmt_int(row["customers"]),
            "active_90d_share": fmt_pct(row["active_90d_share"]),
            "dormant_share": fmt_pct(row["dormant_share"]),
            "avg_annual_spend_czk": f"{fmt_money2(row['avg_annual_spend_czk'])} Kč",
        }
        for row in core_activity_rows
    ]
    quarterly_display = [
        {
            "quarter": row["quarter"],
            "new_customers": fmt_int(row["new_customers"]),
            "return_90d": fmt_pct(row["return_90d"]) if row["return_90d"] is not None else "—",
        }
        for row in quarterly_rows
    ]
    second_purchase_display = [
        {
            "window": row["window"],
            "customers": fmt_int(row["customers"]),
            "share": fmt_pct(row["share"]),
        }
        for row in second_purchase_rows
    ]
    free_shipping_display = [
        {
            "metric": row["metric"],
            "value": f"{fmt_money2(row['value'])} Kč" if "mezera" in row["metric"].lower() else fmt_int(int(row["value"])),
            "share": fmt_pct(row["share"]) if row["share"] is not None else "—",
        }
        for row in free_shipping_rows
    ]
    purchase_progression_display = [
        {
            "purchase_label": row["purchase_label"],
            "orders": fmt_int(row["orders"]),
            "aov_czk": f"{fmt_money2(row['aov_czk'])} Kč",
            "avg_items": f"{row['avg_items']:.2f}",
        }
        for row in purchase_progression_rows
    ]
    weekday_display = [
        {
            "weekday": row["weekday"],
            "orders": fmt_int(row["orders"]),
            "share": fmt_pct(row["share"]),
        }
        for row in weekday_rows
    ]
    hourly_display = [
        {
            "hour": row["hour"],
            "orders": fmt_int(row["orders"]),
            "share": fmt_pct(row["share"]),
        }
        for row in hourly_rows
    ]
    monthly_chart = svg_bar_chart(month_points, label_step=2)
    yearly_chart = svg_grouped_bar_chart(
        [{"label": row["year"], "revenue": row["revenue_czk"], "orders": row["orders"] * 1500} for row in yearly_rows],
        [("revenue", "Tržby", "#9a3412"), ("orders", "Objednávky x 1500", "#0f766e")],
        height=300,
    )
    segment_chart = svg_horizontal_bar_chart(
        [
            {"label": f"{row['band']} objednávek", "value": row["revenue_share"] * 100, "value_label": fmt_pct(row["revenue_share"]), "color": color}
            for row, color in zip(pdf_segment_rows, ["#d97706", "#c2410c", "#0f766e", "#1d4ed8"])
        ],
        height=260,
    )
    quarterly_chart = svg_grouped_bar_chart(
        [{"label": row["quarter"][2:], "new_customers": row["new_customers"], "return_90d": (row["return_90d"] or 0) * 1000} for row in quarterly_rows],
        [("new_customers", "Noví zákazníci", "#9a3412"), ("return_90d", "Návrat do 90 dní x 1000", "#0f766e")],
        height=300,
    )
    second_purchase_chart = svg_horizontal_bar_chart(
        [
            {"label": row["window"], "value": row["share"] * 100, "value_label": fmt_pct(row["share"]), "color": color}
            for row, color in zip(second_purchase_rows, ["#0f766e", "#1d4ed8", "#c2410c", "#7c2d12"])
        ],
        height=260,
        pad_x=220,
    )
    free_shipping_chart = svg_horizontal_bar_chart(
        [
            {"label": "Pod 1 600 Kč", "value": free_shipping_rows[0]["share"] * 100, "value_label": fmt_pct(free_shipping_rows[0]["share"]), "color": "#9a3412"},
            {"label": "Pásmo 1 400–1 600", "value": free_shipping_rows[2]["share"] * 100, "value_label": fmt_pct(free_shipping_rows[2]["share"]), "color": "#0f766e"},
            {"label": "Mediánová mezera", "value": free_shipping_rows[1]["value"], "value_label": f"{fmt_money2(free_shipping_rows[1]['value'])} Kč", "color": "#1d4ed8"},
        ],
        height=220,
        pad_x=220,
    )
    progression_aov_chart = svg_line_chart(
        [{"label": row["purchase_label"], "value": row["aov_czk"]} for row in purchase_progression_rows],
        color="#9a3412",
        fill="#f6e7d2",
    )
    progression_items_chart = svg_line_chart(
        [{"label": row["purchase_label"], "value": row["avg_items"]} for row in purchase_progression_rows],
        color="#0f766e",
        fill="#d9f3ef",
    )
    weekday_chart = svg_bar_chart(
        [{"label": row["weekday"][:2], "value": row["share"] * 100, "color": "#9a3412" if row["weekday"] == strongest_weekday["weekday"] else "#c08457"} for row in weekday_rows],
        height=240,
    )
    hourly_chart = svg_bar_chart(
        [{"label": row["hour"][:2], "value": row["share"] * 100, "color": "#0f766e" if row["hour"] == peak_hour["hour"] else "#7dd3c7"} for row in hourly_rows],
        height=240,
        label_step=2,
    )
    market_chart = svg_grouped_bar_chart(
        [
            {"label": "CZ", "aov": market_diag["CZ"]["aov_czk"], "repeat90": market_diag["CZ"]["first_to_second_90d"] * 3000},
            {"label": "SK", "aov": market_diag["SK"]["aov_czk"], "repeat90": market_diag["SK"]["first_to_second_90d"] * 3000},
        ],
        [("aov", "AOV", "#9a3412"), ("repeat90", "2. nákup do 90 dní x 3000", "#0f766e")],
        height=260,
    )

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
    .lede {{ font-size:18px; line-height:1.5; max-width:860px; }}
    .meta {{ color:var(--muted); font-size:14px; line-height:1.6; margin-bottom:10px; }}
    h1 {{ margin:0 0 10px; font-size:42px; line-height:1.05; }}
    h2 {{ margin:0 0 14px; font-size:24px; }}
    .grid-2 {{ display:grid; grid-template-columns:1.2fr 1fr; gap:18px; margin-top:18px; }}
    .grid-3 {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:18px; margin-top:18px; }}
    .grid-5 {{ display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:12px; margin-top:18px; }}
    ul {{ margin:0; padding-left:20px; line-height:1.7; }}
    table {{ width:100%; border-collapse:collapse; font-size:14px; }}
    th, td {{ padding:10px 8px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; }}
    th {{ font-size:12px; text-transform:uppercase; letter-spacing:.06em; color:var(--muted); }}
    .pill {{ display:inline-block; padding:6px 10px; border-radius:999px; background:var(--soft); color:var(--accent); font-size:13px; margin:0 8px 8px 0; }}
    .cta {{ display:inline-block; padding:10px 14px; border-radius:999px; background:var(--accent); color:#fff; text-decoration:none; font-size:14px; margin-top:12px; }}
    .note {{ color:var(--muted); font-size:13px; line-height:1.6; }}
    .mini-card {{ background:var(--soft); border-radius:18px; padding:14px; }}
    .mini-card strong {{ display:block; font-size:14px; margin-bottom:4px; }}
    details {{ margin-top:12px; }}
    summary {{ cursor:pointer; color:var(--accent); font-size:14px; }}
    a {{ color:var(--accent); text-decoration:none; }}
    @media (max-width: 980px) {{
      .cards, .grid-2, .grid-3, .grid-5 {{ grid-template-columns:1fr; }}
      h1 {{ font-size:34px; }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <section class="hero">
      <div class="meta">Plná analýza | Pokrytí: {orders[0].dt.strftime('%d.%m.%Y %H:%M')} až {latest_dt.strftime('%d.%m.%Y %H:%M')} | Exporty: 2024 + 2025 + H1 2026 | Aktualizováno: {datetime.now().strftime('%d.%m.%Y %H:%M')}</div>
      <h1>TianDe 2024-2026: co se děje, proč se to děje a co s tím</h1>
      <div class="lede">Zkrácená čtecí verze: víc grafů, méně textu. Hlavní otázky jsou tři: kde mizí obrat, jak rychle se vracejí zákazníci a kde je nejrychlejší páka na růst.</div>
      <div style="margin-top:14px;">
        <span class="pill">Kde mizí obrat</span>
        <span class="pill">Kdo se vrací a kdo ne</span>
        <span class="pill">Kde leží nejrychlejší peníze</span>
        <span class="pill">Česko vs Slovensko</span>
        <span class="pill">Co udělat hned</span>
      </div>
      <a class="cta" href="./ceo-one-pager.html">Shrnutí pro vedení</a>
      <a class="cta" href="./tyden-po-tydnu.html" style="margin-left:8px;">Plán týden po týdnu</a>
      <a class="cta" href="https://github.com/rkonfal/tiande-orders-3y-analysis" style="margin-left:8px; background:var(--accent2);">Repo</a>
    </section>

    <section class="cards">
      <div class="card"><div class="kicker">Platné tržby</div><div class="value">{fmt_money(sum(o.total_czk for o in valid_orders))} Kč</div></div>
      <div class="card"><div class="kicker">Platné objednávky</div><div class="value">{fmt_int(len(valid_orders))}</div></div>
      <div class="card"><div class="kicker">Podíl tržeb od vracejících se zákazníků</div><div class="value">{fmt_pct(pct(sum(v['revenue_czk'] for v in customer_stats.values() if v['orders'] >= 2), total_identified_revenue))}</div></div>
      <div class="card"><div class="kicker">Typická mezera mezi objednávkami</div><div class="value">{median(all_gaps) if all_gaps else 0} dní</div></div>
    </section>

    <section class="panel">
      <h2>Rychlé čtení</h2>
      <div class="grid-5">
        <div class="mini-card"><strong>Obrat padá hlavně přes bázi</strong>H1 2026 vs H1 2025: aktivní zákazníci `-16,5 %`, tržby `-10,3 %`.</div>
        <div class="mini-card"><strong>Košík problém není</strong>AOV ve stejném okně vyrostlo na `1 669 Kč`.</div>
        <div class="mini-card"><strong>Byznys táhne jádro</strong>`13+` objednávek dělá `{fmt_pct(next(r['revenue_share'] for r in pdf_segment_rows if r['band']=='13+'))}` identifikovaných tržeb.</div>
        <div class="mini-card"><strong>Návratové okno</strong>Medián do 2. nákupu je `{second_purchase_median}` dní. Kritické okno je `30–90 dní`.</div>
        <div class="mini-card"><strong>Česko vs Slovensko</strong>SK má vyšší AOV, CZ má větší objem. Potřebují jinou práci s košíkem i kampaněmi.</div>
      </div>
    </section>

    <section class="panel">
      <h2>Co udělat hned</h2>
      <div class="grid-5">
        <div class="mini-card"><strong>1. Druhý nákup</strong>0–45 dní po prvním nákupu. Měřit `2. objednávku do 30/60/90 dní`.</div>
        <div class="mini-card"><strong>2. Návrat 1x 91+</strong>Reaktivace jednorázových zákazníků přes bestsellery a jednoduché sety.</div>
        <div class="mini-card"><strong>3. Zvednout CZ košík</strong>Sety, dárek od částky, chytřejší upsell v košíku.</div>
        <div class="mini-card"><strong>4. Chránit top zákazníky</strong>Prioritní nabídky a péče, ne plošné slevy.</div>
        <div class="mini-card"><strong>5. Oddělit CZ a SK</strong>Samostatné kampaně, texty i obchodní nabídka.</div>
      </div>
    </section>

    <section class="panel">
      <h2>Tři roky v číslech</h2>
      <div class="note">Roční přehled: obrat i počet objednávek jdou dolů, ale AOV roste.</div>
      <div style="margin-top:12px;">{yearly_chart}</div>
      <details><summary>Ukázat tabulku</summary>{table(yearly_display, ["year","revenue_czk","orders","customers","aov_czk","revenue_yoy","orders_yoy","customers_yoy"], {
        "year":"Rok",
        "revenue_czk":"Tržby",
        "orders":"Objednávky",
        "customers":"Unikátní zákazníci",
        "aov_czk":"AOV",
        "revenue_yoy":"Tržby meziročně",
        "orders_yoy":"Objednávky meziročně",
        "customers_yoy":"Zákazníci meziročně"
      })}</details>
    </section>

    <section class="grid-2">
      <div class="panel">
        <h2>Měsíční tržby za 30 měsíců</h2>
        <div class="note">Běžné měsíce jsou světle, listopady zvýrazněné jako `Black Friday`, prosince zeleně.</div>
        <div style="margin-top:12px;">{monthly_chart}</div>
        <details><summary>Ukázat tabulku po měsících</summary>{table(monthly_30_display, ["month","month_type","revenue_czk","orders","customers","aov_czk"], {
          "month":"Měsíc",
          "month_type":"Typ",
          "revenue_czk":"Tržby",
          "orders":"Objednávky",
          "customers":"Zákazníci",
          "aov_czk":"AOV"
        })}</details>
      </div>
      <div class="panel">
        <h2>BF pattern</h2>
        <div class="note">Listopad výrazně vystřelí, prosinec pak spadne pod listopad, ale ne pod běžný měsíc.</div>
        <details open><summary>Ukázat BF srovnání</summary>{table(bf_pattern_display, ["year","regular_avg_revenue_czk","november_delta","december_delta"], {
          "year":"Rok",
          "regular_avg_revenue_czk":"Průměr běžného měsíce",
          "november_delta":"Listopad vs běžný měsíc",
          "december_delta":"Prosinec vs běžný měsíc"
        })}</details>
      </div>
    </section>

    <section class="panel">
      <h2>Struktura zákaznické základny</h2>
      <div class="grid-2">
        <div>
          <div class="note">Nejdůležitější je pravý kraj: zákazníci s vysokým počtem objednávek nesou většinu tržeb.</div>
          <div style="margin-top:12px;">{segment_chart}</div>
          <details><summary>Ukázat tabulku segmentů</summary>{table(pdf_segment_display, ["band","customers","revenue_czk","revenue_share"], {
            "band":"Objednávky na zákazníka",
            "customers":"Zákazníci",
            "revenue_czk":"Tržby",
            "revenue_share":"Podíl na tržbách"
          })}</details>
        </div>
        <div>
          <div class="note">Core síť je pořád silná, ale i tady už je vidět dormantní kus báze.</div>
          <details open><summary>Ukázat core přehled</summary>{table(core_activity_display, ["segment","customers","active_90d_share","dormant_share","avg_annual_spend_czk"], {
            "segment":"Core síť",
            "customers":"Zákazníci",
            "active_90d_share":"Aktivní za 90 dní",
            "dormant_share":"Dormantní podíl",
            "avg_annual_spend_czk":"Průměrná roční útrata"
          })}</details>
          <div class="note" style="margin-top:10px;">Průměrná roční útrata je annualizovaná přes celé pozorované okno `2024-01` až `2026-06`.</div>
        </div>
      </div>
    </section>

    <section class="grid-2">
      <div class="panel">
        <h2>Akvizice po kvartálech</h2>
        <div style="margin-top:12px;">{quarterly_chart}</div>
        <details><summary>Ukázat kvartální tabulku</summary>{table(quarterly_display, ["quarter","new_customers","return_90d"], {
          "quarter":"Kvartál 1. nákupu",
          "new_customers":"Noví zákazníci",
          "return_90d":"Návrat do 90 dní"
        })}</details>
      </div>
      <div class="panel">
        <h2>Rychlost návratu k 2. nákupu</h2>
        <div style="margin-top:12px;">{second_purchase_chart}</div>
        <details><summary>Ukázat návratová okna</summary>{table(second_purchase_display, ["window","customers","share"], {
          "window":"Nákupní okno",
          "customers":"Zákazníci",
          "share":"Podíl"
        })}</details>
        <div class="note" style="margin-top:10px;">Medián do 2. nákupu je `{second_purchase_median}` dní. To je čisté order-level číslo nad zákazníky, kde už se druhý nákup opravdu objevil.</div>
      </div>
    </section>

    <section class="grid-2">
      <div class="panel">
        <h2>Doprava zdarma</h2>
        <div style="margin-top:12px;">{free_shipping_chart}</div>
        <details><summary>Ukázat detail</summary>{table(free_shipping_display, ["metric","value","share"], {
          "metric":"Metrika",
          "value":"Hodnota",
          "share":"Podíl objednávek"
        })}</details>
      </div>
      <div class="panel">
        <h2>Jak roste zákazník</h2>
        <div class="note">Čím víc nákupů za sebou, tím větší košík i vyšší AOV.</div>
        <div style="margin-top:12px;">{progression_aov_chart}</div>
        <div style="margin-top:12px;">{progression_items_chart}</div>
        <details><summary>Ukázat tabulku</summary>{table(purchase_progression_display, ["purchase_label","orders","aov_czk","avg_items"], {
          "purchase_label":"Pořadí nákupu",
          "orders":"Pozorované objednávky",
          "aov_czk":"Průměrná objednávka",
          "avg_items":"Prům. počet položek"
        })}</details>
      </div>
    </section>

    <section class="grid-2">
      <div class="panel">
        <h2>Nákupní chování podle dnů</h2>
        <div style="margin-top:12px;">{weekday_chart}</div>
        <details><summary>Ukázat tabulku</summary>{table(weekday_display, ["weekday","orders","share"], {
          "weekday":"Den",
          "orders":"Objednávky",
          "share":"Podíl"
        })}</details>
        <div class="note" style="margin-top:10px;">Nejsilnější den je `{strongest_weekday['weekday']}` ({fmt_pct(strongest_weekday['share'])}), nejslabší je `{weakest_weekday['weekday']}` ({fmt_pct(weakest_weekday['share'])}).</div>
      </div>
      <div class="panel">
        <h2>Nákupní chování podle hodin</h2>
        <div style="margin-top:12px;">{hourly_chart}</div>
        <details><summary>Ukázat tabulku</summary>{table(hourly_display, ["hour","orders","share"], {
          "hour":"Hodina",
          "orders":"Objednávky",
          "share":"Podíl"
        })}</details>
        <div class="note" style="margin-top:10px;">Peak hodina je `{peak_hour['hour']}`. Slot `18:00–21:59` dělá `{fmt_pct(evening_share)}` všech objednávek.</div>
      </div>
    </section>

    <section class="panel">
      <h2>1. Proč je rok 2026 slabší</h2>
      <div class="note">Tržby se tady rozpadají na tři hlavní části: počet aktivních zákazníků, kolikrát nakoupí a jak velkou mají objednávku. Srovnání je ve stejném časovém okně `1. 1. – 29. 6. 15:44` v `2025` a `2026`.</div>
      <details><summary>Ukázat rozpad propadu</summary>{table(driver_display, ["market","active_customers_2025","active_customers_2026","active_customers_delta","orders_per_customer_2025","orders_per_customer_2026","orders_per_customer_delta","aov_2025","aov_2026","aov_delta","revenue_2025","revenue_2026","revenue_delta"], {
        "market":"Trh",
        "active_customers_2025":"Aktivní zákazníci 2025",
        "active_customers_2026":"Aktivní zákazníci 2026",
        "active_customers_delta":"Změna zákazníků",
        "orders_per_customer_2025":"Objednávky na zákazníka 2025",
        "orders_per_customer_2026":"Objednávky na zákazníka 2026",
        "orders_per_customer_delta":"Změna četnosti",
        "aov_2025":"Průměrná objednávka 2025",
        "aov_2026":"Průměrná objednávka 2026",
        "aov_delta":"Změna průměrné objednávky",
        "revenue_2025":"Tržby 2025",
        "revenue_2026":"Tržby 2026",
        "revenue_delta":"Změna tržeb"
      })}</details>
      <div class="note" style="margin-top:10px;">Jednoduše řečeno: když ubývá aktivních zákazníků a zároveň se nezrychluje další nákup, nestačí přikoupit reklamu. Je potřeba řešit kvalitu nových zákazníků i návrat těch stávajících.</div>
    </section>

    <section class="panel">
      <h2>2. Jak se vracejí zákazníci podle měsíce prvního nákupu</h2>
      <div class="note">Každý řádek je měsíc prvního nákupu. Tohle ukazuje, jestli novější skupiny zákazníků jsou lepší, nebo horší než dřív.</div>
      <details><summary>Ukázat kohortovou tabulku</summary>{table(cohort_display, ["cohort","customers","first_order_revenue_czk","rate_30d","rate_60d","rate_90d","rate_180d","third_order_90d"], {
        "cohort":"Měsíc 1. nákupu",
        "customers":"Zákazníci",
        "first_order_revenue_czk":"Tržby z 1. nákupu",
        "rate_30d":"2. nákup do 30 dní",
        "rate_60d":"2. nákup do 60 dní",
        "rate_90d":"2. nákup do 90 dní",
        "rate_180d":"2. nákup do 180 dní",
        "third_order_90d":"3. nákup do 90 dní od 2."
      })}</details>
      <div class="note" style="margin-top:10px;">Praktický závěr: sleduj hlavně nové měsíce. Pokud se zhoršuje druhý nákup do `90 dní`, je problém už v kvalitě prvního nákupu nebo v prvních navazujících kampaních.</div>
    </section>

    <section class="grid-2">
      <div class="panel">
        <h2>3. Kde leží nejrychlejší peníze</h2>
        <details><summary>Ukázat segmenty příležitostí</summary>{table(opp_display, ["segment","customers","segment_revenue_czk","avg_aov_czk","avg_recency_days","expected_conversion","estimated_incremental_revenue_czk","priority"], {
          "segment":"Skupina",
          "customers":"Zákazníci",
          "segment_revenue_czk":"Tržby skupiny",
          "avg_aov_czk":"Průměrná objednávka",
          "avg_recency_days":"Prům. dny od posledního nákupu",
          "expected_conversion":"Odhad návratu",
          "estimated_incremental_revenue_czk":"Odhad obratu navíc",
          "priority":"Priorita"
        })}</details>
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
        <details><summary>Ukázat koncentraci obratu</summary>{table(conc_display, ["bucket","customers","revenue_share"], {
          "bucket":"Skupina",
          "customers":"Zákazníci",
          "revenue_share":"Podíl na tržbách"
        })}</details>
        <div class="note" style="margin-top:10px;">Nejlepších `1 %` zákazníků dělá `{fmt_pct(next(r['revenue_share'] for r in concentration_rows if r['bucket']=='top_1pct'))}` obratu. To je velká páka, ale i riziko. Když tahle skupina oslabí, pocítí to celý byznys.</div>
      </div>
      <div class="panel">
        <h2>Kolik vydělávají zákazníci podle počtu objednávek</h2>
        <details><summary>Ukázat tabulku pásem</summary>{table(tier_display, ["band","customers","revenue_czk","revenue_share"], {
          "band":"Objednávky na zákazníka",
          "customers":"Zákazníci",
          "revenue_czk":"Tržby",
          "revenue_share":"Podíl na tržbách"
        })}</details>
      </div>
    </section>

    <section class="panel">
      <h2>5. Česko vs Slovensko</h2>
      <div class="note">SK má silnější ekonomiku objednávky, CZ zase objem. To není jeden trh, ale dva různé režimy.</div>
      <div style="margin-top:12px;">{market_chart}</div>
      <details><summary>Ukázat tabulku CZ vs SK</summary>{table(market_display, ["market","customers","revenue_czk","orders","aov_czk","avg_items_per_order","median_customer_ltv","first_to_second_90d","seen_before_order_share"], {
        "market":"Trh",
        "customers":"Zákazníci",
        "revenue_czk":"Tržby",
        "orders":"Objednávky",
        "aov_czk":"Průměrná objednávka",
        "avg_items_per_order":"Prům. počet položek",
        "median_customer_ltv":"Medián hodnoty zákazníka",
        "first_to_second_90d":"2. nákup do 90 dní",
        "seen_before_order_share":"Podíl dříve viděných"
      })}</details>
      <div class="note" style="margin-top:10px;">Slovensko není silnější náhodou. Má vyšší průměrnou objednávku a podobnou rychlost návratu. Česko proto nepotřebuje jen víc objednávek, ale hlavně vyšší hodnotu košíku.</div>
    </section>

    <section class="panel">
      <h2>6. Vývoj po měsících</h2>
      {table(yoy_focus_display, ["month","market","customers","orders","revenue_czk","aov_czk","orders_yoy","revenue_yoy"], {
        "month":"Měsíc",
        "market":"Trh",
        "customers":"Zákazníci",
        "orders":"Objednávky",
        "revenue_czk":"Tržby",
        "aov_czk":"Průměrná objednávka",
        "orders_yoy":"Objednávky meziročně",
        "revenue_yoy":"Tržby meziročně"
      })}
    </section>

    <section class="grid-2">
      <div class="panel">
        <h2>7. Přehled zákazníků podle čerstvosti a počtu nákupů</h2>
        {table(rfm_display, ["recency_bucket","frequency_bucket","customers","revenue_czk","revenue_share"], {
          "recency_bucket":"Jak dávno nakoupil",
          "frequency_bucket":"Kolikrát nakoupil",
          "customers":"Zákazníci",
          "revenue_czk":"Tržby",
          "revenue_share":"Podíl na tržbách"
        })}
      </div>
      <div class="panel">
        <h2>8. Datové odchylky a jejich dopad</h2>
        {table(quality_display, ["flag","orders","revenue_czk","revenue_share_of_topline"], {
          "flag":"Odchylka",
          "orders":"Objednávky",
          "revenue_czk":"Tržby",
          "revenue_share_of_topline":"Podíl na tržbách"
        })}
        <div class="note" style="margin-top:10px;">Důležité: `první viděná objednávka` neznamená nutně první objednávku v životě zákazníka. Znamená jen první objednávku v datech, která máme za roky 2024–2026. Rok 2024 je proto potřeba číst opatrně.</div>
      </div>
    </section>

    <section class="panel">
      <h2>9. Co může ještě letos zvednout výsledek</h2>
      {table(scenario_display, ["scenario","first_to_second_90d","reactivation_1x_91d","cz_aov_uplift","estimated_incremental_revenue_czk"], {
        "scenario":"Scénář",
        "first_to_second_90d":"2. nákup do 90 dní",
        "reactivation_1x_91d":"Návrat 1x 91+ dní",
        "cz_aov_uplift":"Zvýšení českého košíku",
        "estimated_incremental_revenue_czk":"Odhad obratu navíc"
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
        <li><a href="./yearly_metrics.csv">yearly_metrics.csv</a></li>
        <li><a href="./monthly_metrics.csv">monthly_metrics.csv</a></li>
        <li><a href="./bf_pattern.csv">bf_pattern.csv</a></li>
        <li><a href="./customer_segment_structure.csv">customer_segment_structure.csv</a></li>
        <li><a href="./core_customer_network.csv">core_customer_network.csv</a></li>
        <li><a href="./quarterly_acquisition_retention.csv">quarterly_acquisition_retention.csv</a></li>
        <li><a href="./second_purchase_windows.csv">second_purchase_windows.csv</a></li>
        <li><a href="./free_shipping_gap.csv">free_shipping_gap.csv</a></li>
        <li><a href="./purchase_progression.csv">purchase_progression.csv</a></li>
        <li><a href="./weekday_behavior.csv">weekday_behavior.csv</a></li>
        <li><a href="./hourly_behavior.csv">hourly_behavior.csv</a></li>
        <li><a href="./cohort_retention.csv">cohort_retention.csv</a></li>
        <li><a href="./driver_decomposition.csv">driver_decomposition.csv</a></li>
        <li><a href="./segment_opportunities.csv">segment_opportunities.csv</a></li>
        <li><a href="./value_concentration.csv">value_concentration.csv</a></li>
        <li><a href="./customer_value_tiers.csv">customer_value_tiers.csv</a></li>
        <li><a href="./market_month_bridge.csv">market_month_bridge.csv</a></li>
        <li><a href="./rfm_matrix.csv">rfm_matrix.csv</a></li>
        <li><a href="./scenario_model.csv">scenario_model.csv</a></li>
        <li><a href="./tyden-po-tydnu.html">plán týden po týdnu</a></li>
      </ul>
      <div class="note" style="margin-top:10px;">Produktové tabulky typu `view → purchase`, sweet spot ceny podle konkrétních SKU a přesný ceníkový audit `Kč / ks` tu záměrně nejsou vydávané za hotové. Ty chtějí item-level order lines a web/CRM eventy, ne jen order-level CSV.</div>
    </section>
  </div>
</body>
</html>
"""
    (DOCS_DIR / "deep-dive.html").write_text(html_page, encoding="utf-8")
    (DOCS_DIR / "index.html").write_text(html_page, encoding="utf-8")

    weekly_html = """<!doctype html>
<html lang="cs">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>TianDe | Plán týden po týdnu</title>
  <style>
    :root {
      --bg: #f4efe7;
      --surface: #fffdf8;
      --line: #e7dccb;
      --ink: #201814;
      --muted: #6d6259;
      --accent: #9a3412;
      --soft: #f6e7d2;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background:
        radial-gradient(circle at top left, rgba(154, 52, 18, 0.10), transparent 28%),
        radial-gradient(circle at top right, rgba(15, 118, 110, 0.10), transparent 24%),
        var(--bg);
      color: var(--ink);
      font-family: Georgia, "Iowan Old Style", "Palatino Linotype", serif;
    }
    .wrap { max-width: 1160px; margin: 0 auto; padding: 28px; }
    .hero, .panel, .week {
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 24px;
      box-shadow: 0 10px 34px rgba(32, 24, 20, 0.05);
    }
    .hero, .panel, .week { padding: 24px; margin-bottom: 18px; }
    h1 { margin: 0 0 10px; font-size: 40px; line-height: 1.05; }
    h2 { margin: 0 0 12px; font-size: 24px; }
    h3 { margin: 0 0 10px; font-size: 18px; }
    .meta, .note { color: var(--muted); font-size: 14px; line-height: 1.6; }
    .grid-2 { display:grid; grid-template-columns:1fr 1fr; gap:18px; }
    ul { margin: 0; padding-left: 20px; line-height: 1.7; }
    table { width: 100%; border-collapse: collapse; font-size: 14px; }
    th, td { padding: 10px 8px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }
    th { font-size: 12px; text-transform: uppercase; letter-spacing: .06em; color: var(--muted); }
    .pill { display:inline-block; padding:6px 10px; border-radius:999px; background:var(--soft); color:var(--accent); font-size:13px; margin:0 8px 8px 0; }
    a { color: var(--accent); text-decoration:none; }
    @media (max-width: 980px) { .grid-2 { grid-template-columns:1fr; } h1 { font-size: 34px; } }
  </style>
</head>
<body>
  <div class="wrap">
    <section class="hero">
      <div class="meta">Praktický provozní plán navázaný na 3letou analýzu TianDe objednávek</div>
      <h1>Jak to řídit týden po týdnu</h1>
      <div class="note">Tohle není další analýza. Tohle je provozní plán, jak zjištění převést do práce každý týden. Cíl je jednoduchý: vrátit více lidí k druhé objednávce, vytáhnout český košík, ochránit nejlepší zákazníky a zastavit odliv aktivní báze.</div>
      <div style="margin-top:14px;">
        <span class="pill">druhý nákup</span>
        <span class="pill">návrat starých zákazníků</span>
        <span class="pill">český košík</span>
        <span class="pill">nejlepší zákazníci</span>
      </div>
    </section>

    <section class="grid-2">
      <div class="panel">
        <h2>4 hlavní proudy práce</h2>
        <ul>
          <li><strong>Druhý nákup:</strong> každý nový zákazník musí co nejrychleji dostat důvod vrátit se.</li>
          <li><strong>Třetí a další nákupy:</strong> lidi, kteří už nakoupili 2x až 4x, je potřeba převést do pravidelného návyku.</li>
          <li><strong>Český košík:</strong> v Česku je potřeba zvednout hodnotu objednávky přes sety, doplnění a dárek od určité částky.</li>
          <li><strong>Nejlepší zákazníci:</strong> malá skupina lidí dělá velkou část obratu, proto musí mít zvláštní péči.</li>
        </ul>
      </div>
      <div class="panel">
        <h2>Co hlídat pořád dokola</h2>
        <ul>
          <li>2. objednávka do 30 / 60 / 90 dní</li>
          <li>3. objednávka do 90 dní od druhé</li>
          <li>návrat lidí po 46–90 dnech a po 91+ dnech</li>
          <li>průměrná hodnota objednávky v Česku a na Slovensku</li>
          <li>počet aktivních nejlepších zákazníků</li>
        </ul>
      </div>
    </section>

    <section class="week">
      <h2>Týdny 1 až 2</h2>
      <ul>
        <li>Vytáhnout seznam lidí po 1. nákupu: `0–14 dní`, `15–45 dní`, `46–90 dní`, `91+ dní`.</li>
        <li>Vytáhnout seznam nejlepších zákazníků a označit ty, kteří delší dobu nenakoupili.</li>
        <li>Rozdělit komunikaci na Česko a Slovensko.</li>
        <li>Připravit první dvě návratové vlny: druhý nákup a návrat `46–90 dní`.</li>
      </ul>
    </section>

    <section class="week">
      <h2>Týdny 3 až 4</h2>
      <ul>
        <li>Spustit kampaň na druhý nákup pro lidi do 45 dní po prvním nákupu.</li>
        <li>Spustit návratovou kampaň pro skupinu `46–90 dní`.</li>
        <li>V Česku nasadit první sety a dárek od určité částky.</li>
        <li>Každý týden zkontrolovat, jestli se zlepšuje druhý nákup a český košík.</li>
      </ul>
    </section>

    <section class="week">
      <h2>Týdny 5 až 6</h2>
      <ul>
        <li>Spustit silnou návratovou kampaň pro skupinu `91+ dní`.</li>
        <li>U nejlepších zákazníků nasadit přednostní nabídky, dárky a osobnější péči.</li>
        <li>Vyhodnotit, jestli lépe funguje set, dárek od určité částky nebo doprava zdarma.</li>
        <li>Na Slovensku zkusit zvláštní návratovou nabídku, protože tam je objednávka hodnotnější.</li>
      </ul>
    </section>

    <section class="week">
      <h2>Týdny 7 až 8</h2>
      <ul>
        <li>Podívat se, které první produkty nejčastěji vedou k druhému nákupu a které naopak končí slepě.</li>
        <li>Posílit nabídku kolem produktů, které vedou k dalším objednávkám.</li>
        <li>Omezit nebo přepsat první nabídku tam, kde lidé po prvním nákupu mizí.</li>
        <li>Porovnat výsledky Česka a Slovenska zvlášť, ne dohromady.</li>
      </ul>
    </section>

    <section class="week">
      <h2>Týdny 9 až 10</h2>
      <ul>
        <li>Převést vítězné kampaně do pravidelného režimu.</li>
        <li>Rozšířit práci s lidmi, kteří nakoupili 2x až 4x, aby rychleji udělali další objednávku.</li>
        <li>Zkontrolovat, jestli se zvedá český košík bez toho, aby spadla marže.</li>
      </ul>
    </section>

    <section class="week">
      <h2>Týdny 11 až 12</h2>
      <ul>
        <li>Vyhodnotit celé čtvrtletí: co zvedlo druhý nákup, co vrátilo staré zákazníky a co zvedlo český košík.</li>
        <li>Rozhodnout, jestli další čtvrtletí dál tlačit hlavně návrat zákazníků, nebo už znovu víc přidat do získávání nových lidí.</li>
        <li>Udělat finální rozdělení na to, co poběží stále, a co byl jen jednorázový test.</li>
      </ul>
    </section>

    <section class="panel">
      <h2>Rytmus řízení</h2>
      <table>
        <thead><tr><th>Kdy</th><th>Co udělat</th></tr></thead>
        <tbody>
          <tr><td>1x týdně</td><td>Zkontrolovat druhý nákup, návrat jednorázových zákazníků, český košík a aktivitu nejlepších zákazníků.</td></tr>
          <tr><td>1x za 14 dní</td><td>Vyhodnotit nabídky: set, dárek od určité částky, doprava zdarma, návrat přes bestseller.</td></tr>
          <tr><td>1x měsíčně</td><td>Porovnat Česko a Slovensko a rozhodnout, která skupina slábne a kde je potřeba přitlačit.</td></tr>
        </tbody>
      </table>
    </section>
  </div>
</body>
</html>
"""
    (DOCS_DIR / "tyden-po-tydnu.html").write_text(weekly_html, encoding="utf-8")


if __name__ == "__main__":
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    build()
