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
ASSETS_DIR = DOCS_DIR / "assets"
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
    year_file: str
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


def order_market(row: dict) -> str:
    country = (row.get("delivery_country_code") or row.get("country_code") or "").strip().upper()
    return "SK" if country == "SK" else "CZ"


def counted_flag(row: dict) -> bool:
    return (row.get("is_counted") or "").strip().lower() in {"t", "true", "1", "yes", "y"}


def load_orders():
    orders = []
    file_summaries = []
    for path in SOURCE_FILES:
        count = 0
        min_dt = None
        max_dt = None
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                dt = datetime.fromisoformat(row["order_created_at_prague"])
                count += 1
                min_dt = dt if min_dt is None or dt < min_dt else min_dt
                max_dt = dt if max_dt is None or dt > max_dt else max_dt
                orders.append(
                    OrderRow(
                        order_id=(row.get("order_id") or "").strip(),
                        dt=dt,
                        raw_customer_id=(row.get("customer_id") or "").strip(),
                        raw_email=normalize_email(row.get("customer_email") or ""),
                        market=order_market(row),
                        status_id=(row.get("status_id") or "").strip(),
                        total_czk=parse_float(row.get("order_total_czk") or ""),
                        items_count=parse_int(row.get("items_count") or ""),
                        currency=(row.get("currency") or "").strip().upper(),
                        year_file=path.name,
                        is_counted=counted_flag(row),
                    )
                )
        file_summaries.append(
            {
                "file": path.name,
                "rows": count,
                "date_min": min_dt.isoformat(sep=" "),
                "date_max": max_dt.isoformat(sep=" "),
                "size_mb": round(path.stat().st_size / (1024 * 1024), 2),
            }
        )
    orders.sort(key=lambda row: (row.dt, row.order_id))
    return orders, file_summaries


def attach_customer_keys(orders):
    email_to_ids = defaultdict(set)
    for order in orders:
        if order.raw_customer_id and order.raw_email:
            email_to_ids[order.raw_email].add(order.raw_customer_id)

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
    return customer_keys


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


def fmt_money(value: float) -> str:
    return f"{value:,.0f}".replace(",", " ")


def fmt_money2(value: float) -> str:
    return f"{value:,.2f}".replace(",", " ")


def fmt_pct(value: float) -> str:
    return f"{value * 100:.1f} %"


def pct(num: float, den: float) -> float:
    return num / den if den else 0.0


def write_csv(path: Path, rows, fieldnames):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def svg_line_chart(points, width=920, height=320, color="#1d4ed8", fill="#dbeafe"):
    if not points:
        return "<svg viewBox='0 0 920 320'></svg>"
    values = [point["value"] for point in points]
    labels = [point["label"] for point in points]
    max_value = max(values) or 1
    min_value = min(values)
    span = max_value - min_value or 1
    pad_x = 56
    pad_y = 24
    plot_w = width - pad_x * 2
    plot_h = height - pad_y * 2
    coords = []
    for index, point in enumerate(points):
        x = pad_x + (plot_w * index / max(1, len(points) - 1))
        y = pad_y + plot_h - ((point["value"] - min_value) / span) * plot_h
        coords.append((x, y))
    polyline = " ".join(f"{x:.2f},{y:.2f}" for x, y in coords)
    area = f"{pad_x},{height - pad_y} " + polyline + f" {coords[-1][0]:.2f},{height - pad_y}"
    y_ticks = []
    for i in range(5):
        ratio = i / 4
        val = max_value - ratio * span
        y = pad_y + plot_h * ratio
        y_ticks.append(
            f"<g><line x1='{pad_x}' y1='{y:.2f}' x2='{width - pad_x}' y2='{y:.2f}' stroke='#e2e8f0'/>"
            f"<text x='8' y='{y + 4:.2f}' font-size='12' fill='#64748b'>{html.escape(fmt_money(val))}</text></g>"
        )
    x_ticks = []
    step = max(1, math.ceil(len(labels) / 8))
    for idx, label in enumerate(labels):
        if idx % step:
            continue
        x = coords[idx][0]
        x_ticks.append(
            f"<text x='{x:.2f}' y='{height - 6}' text-anchor='middle' font-size='11' fill='#64748b'>{html.escape(label)}</text>"
        )
    return (
        f"<svg viewBox='0 0 {width} {height}' role='img' aria-label='chart'>"
        f"{''.join(y_ticks)}"
        f"<polygon points='{area}' fill='{fill}' opacity='0.9'></polygon>"
        f"<polyline points='{polyline}' fill='none' stroke='{color}' stroke-width='3'></polyline>"
        + "".join(
            f"<circle cx='{x:.2f}' cy='{y:.2f}' r='4' fill='{color}'></circle>" for x, y in coords
        )
        + "".join(x_ticks)
        + "</svg>"
    )


def svg_stacked_share_chart(points, width=920, height=320):
    if not points:
        return "<svg viewBox='0 0 920 320'></svg>"
    pad_x = 56
    pad_y = 20
    plot_w = width - pad_x * 2
    plot_h = height - pad_y * 2
    bar_w = plot_w / len(points)
    parts = []
    step = max(1, math.ceil(len(points) / 8))
    for i, point in enumerate(points):
        x = pad_x + i * bar_w + 2
        repeat_h = plot_h * point["repeat_share"]
        new_h = plot_h - repeat_h
        repeat_y = pad_y + new_h
        parts.append(
            f"<rect x='{x:.2f}' y='{repeat_y:.2f}' width='{bar_w - 4:.2f}' height='{repeat_h:.2f}' fill='#059669'></rect>"
            f"<rect x='{x:.2f}' y='{pad_y:.2f}' width='{bar_w - 4:.2f}' height='{new_h:.2f}' fill='#f59e0b'></rect>"
        )
        if i % step == 0:
            parts.append(
                f"<text x='{x + (bar_w - 4) / 2:.2f}' y='{height - 6}' text-anchor='middle' font-size='11' fill='#64748b'>{html.escape(point['label'])}</text>"
            )
    parts.extend(
        [
            f"<line x1='{pad_x}' y1='{pad_y}' x2='{pad_x}' y2='{height - pad_y}' stroke='#cbd5e1'/>",
            f"<line x1='{pad_x}' y1='{height - pad_y}' x2='{width - pad_x}' y2='{height - pad_y}' stroke='#cbd5e1'/>",
            f"<text x='8' y='{pad_y + 4}' font-size='12' fill='#64748b'>100 %</text>",
            f"<text x='18' y='{height - pad_y + 4}' font-size='12' fill='#64748b'>0 %</text>",
        ]
    )
    return f"<svg viewBox='0 0 {width} {height}'>{''.join(parts)}</svg>"


def build_report():
    orders, file_summaries = load_orders()
    customer_keys = attach_customer_keys(orders)
    latest_dt = max(order.dt for order in orders)
    snapshot_date = latest_dt.date()

    valid_orders = [
        order
        for order in orders
        if order.is_counted and order.status_id in VALID_STATUS_IDS and order.total_czk > 0
    ]
    anonymous_valid = [order for order in valid_orders if not customer_keys[order.order_id]]
    identified_valid = [order for order in valid_orders if customer_keys[order.order_id]]

    customers = defaultdict(list)
    for order in identified_valid:
        customers[customer_keys[order.order_id]].append(order)

    customer_stats = {}
    revenue_values = []
    aov_values = []
    days_between_first_second = []
    days_between_second_third = []
    monthly_metrics = defaultdict(
        lambda: {
            "month": "",
            "valid_orders": 0,
            "valid_revenue_czk": 0.0,
            "identified_orders": 0,
            "identified_revenue_czk": 0.0,
            "new_customer_orders": 0,
            "new_customer_revenue_czk": 0.0,
            "repeat_orders": 0,
            "repeat_revenue_czk": 0.0,
            "new_customers": set(),
            "repeat_customers": set(),
        }
    )
    country_metrics = defaultdict(
        lambda: {
            "market": "",
            "orders": 0,
            "revenue_czk": 0.0,
            "identified_orders": 0,
            "identified_revenue_czk": 0.0,
            "customers": set(),
            "repeat_orders": 0,
            "repeat_revenue_czk": 0.0,
        }
    )
    quality_flags = Counter()
    weird_revenue_samples = []
    customer_order_bands = Counter()

    for order in orders:
        if order.total_czk == 0:
            quality_flags["zero_value_orders"] += 1
        if 0 < order.total_czk <= 1:
            quality_flags["orders_up_to_1_czk"] += 1
        if order.status_id == "8":
            quality_flags["error_status_orders"] += 1
        if order.market == "SK" and order.currency == "CZK":
            quality_flags["sk_orders_with_czk_currency"] += 1
        if order.market == "CZ" and order.currency == "EUR":
            quality_flags["cz_orders_with_eur_currency"] += 1
        if order.total_czk < 0:
            weird_revenue_samples.append(
                {"order_id": order.order_id, "dt": order.dt.isoformat(sep=" "), "value_czk": order.total_czk}
            )

    for customer, customer_orders in customers.items():
        customer_orders.sort(key=lambda row: (row.dt, row.order_id))
        total_revenue = sum(order.total_czk for order in customer_orders)
        order_count = len(customer_orders)
        avg_order_value = total_revenue / order_count
        first_dt = customer_orders[0].dt
        last_dt = customer_orders[-1].dt
        recency_days = (snapshot_date - last_dt.date()).days
        customer_stats[customer] = {
            "orders": order_count,
            "revenue_czk": total_revenue,
            "avg_order_value_czk": avg_order_value,
            "first_dt": first_dt,
            "last_dt": last_dt,
            "recency_days": recency_days,
            "first_value_czk": customer_orders[0].total_czk,
        }
        revenue_values.append(total_revenue)
        aov_values.append(avg_order_value)

        if order_count == 1:
            customer_order_bands["1"] += 1
        elif order_count == 2:
            customer_order_bands["2"] += 1
        elif order_count == 3:
            customer_order_bands["3"] += 1
        elif 4 <= order_count <= 5:
            customer_order_bands["4-5"] += 1
        else:
            customer_order_bands["6+"] += 1

        for index, order in enumerate(customer_orders):
            month = order.dt.strftime("%Y-%m")
            monthly = monthly_metrics[month]
            monthly["month"] = month
            monthly["identified_orders"] += 1
            monthly["identified_revenue_czk"] += order.total_czk
            monthly["new_customers" if index == 0 else "repeat_customers"].add(customer)
            if index == 0:
                monthly["new_customer_orders"] += 1
                monthly["new_customer_revenue_czk"] += order.total_czk
            else:
                monthly["repeat_orders"] += 1
                monthly["repeat_revenue_czk"] += order.total_czk

            cstats = country_metrics[order.market]
            cstats["market"] = order.market
            cstats["identified_orders"] += 1
            cstats["identified_revenue_czk"] += order.total_czk
            cstats["customers"].add(customer)
            if index > 0:
                cstats["repeat_orders"] += 1
                cstats["repeat_revenue_czk"] += order.total_czk

        if order_count >= 2:
            days_between_first_second.append((customer_orders[1].dt - customer_orders[0].dt).days)
        if order_count >= 3:
            days_between_second_third.append((customer_orders[2].dt - customer_orders[1].dt).days)

    for order in valid_orders:
        month = order.dt.strftime("%Y-%m")
        monthly = monthly_metrics[month]
        monthly["month"] = month
        monthly["valid_orders"] += 1
        monthly["valid_revenue_czk"] += order.total_czk
        cstats = country_metrics[order.market]
        cstats["market"] = order.market
        cstats["orders"] += 1
        cstats["revenue_czk"] += order.total_czk

    revenue_vip_threshold = quantile(revenue_values, 0.9)
    aov_high_threshold = quantile(aov_values, 0.9)

    segments = Counter()
    for stats in customer_stats.values():
        if stats["orders"] == 1:
            if stats["recency_days"] <= 14:
                segments["1x_0_14d"] += 1
            elif stats["recency_days"] <= 45:
                segments["1x_15_45d"] += 1
            elif stats["recency_days"] <= 90:
                segments["1x_46_90d"] += 1
            else:
                segments["1x_91d_plus"] += 1
        if 2 <= stats["orders"] <= 4 and stats["recency_days"] <= 45:
            segments["repeat_2_4_active_45d"] += 1
        if 2 <= stats["orders"] <= 4 and 46 <= stats["recency_days"] <= 90:
            segments["repeat_2_4_lapse_46_90d"] += 1
        if stats["revenue_czk"] >= revenue_vip_threshold and stats["recency_days"] <= 60:
            segments["vip_active"] += 1
        if stats["revenue_czk"] >= revenue_vip_threshold and stats["recency_days"] > 60:
            segments["vip_dormant"] += 1
        if (
            stats["avg_order_value_czk"] >= aov_high_threshold
            and stats["orders"] <= 3
            and stats["recency_days"] <= 180
        ):
            segments["high_aov_low_frequency"] += 1

    def transition_stats(position: int, window_days: int):
        denom = 0
        num = 0
        within_window_deltas = []
        threshold = latest_dt - timedelta(days=window_days)
        for customer_orders in customers.values():
            if len(customer_orders) <= position - 1:
                continue
            reference_dt = customer_orders[position - 1].dt
            if reference_dt > threshold:
                continue
            denom += 1
            if len(customer_orders) > position:
                delta = (customer_orders[position].dt - reference_dt).days
                if delta <= window_days:
                    num += 1
                    within_window_deltas.append(delta)
        return {
            "position": position,
            "window_days": window_days,
            "eligible_customers": denom,
            "converted_customers": num,
            "rate": pct(num, denom),
            "median_days_if_within_window": median(within_window_deltas) if within_window_deltas else None,
        }

    transition_rows = []
    for position in (1, 2):
        for window_days in (30, 60, 90):
            transition_rows.append(transition_stats(position, window_days))

    monthly_rows = []
    for month in sorted(monthly_metrics):
        row = monthly_metrics[month]
        row["new_customers"] = len(row["new_customers"])
        row["repeat_customers"] = len(row["repeat_customers"])
        row["repeat_order_share"] = round(pct(row["repeat_orders"], row["identified_orders"]), 4)
        row["repeat_revenue_share"] = round(pct(row["repeat_revenue_czk"], row["identified_revenue_czk"]), 4)
        monthly_rows.append(row)

    yearly_rollup = defaultdict(
        lambda: {
            "year": "",
            "valid_orders": 0,
            "valid_revenue_czk": 0.0,
            "identified_orders": 0,
            "identified_revenue_czk": 0.0,
            "new_customer_orders": 0,
            "repeat_orders": 0,
            "new_customers": 0,
        }
    )
    for row in monthly_rows:
        year = row["month"][:4]
        target = yearly_rollup[year]
        target["year"] = year
        target["valid_orders"] += row["valid_orders"]
        target["valid_revenue_czk"] += row["valid_revenue_czk"]
        target["identified_orders"] += row["identified_orders"]
        target["identified_revenue_czk"] += row["identified_revenue_czk"]
        target["new_customer_orders"] += row["new_customer_orders"]
        target["repeat_orders"] += row["repeat_orders"]
        target["new_customers"] += row["new_customers"]
    yearly_rows = []
    for year in sorted(yearly_rollup):
        row = yearly_rollup[year]
        row["repeat_order_share"] = round(pct(row["repeat_orders"], row["identified_orders"]), 4)
        row["repeat_revenue_share"] = round(
            pct(
                row["identified_revenue_czk"] - sum(
                    month["new_customer_revenue_czk"] for month in monthly_rows if month["month"].startswith(year)
                ),
                row["identified_revenue_czk"],
            ),
            4,
        )
        yearly_rows.append(row)

    country_rows = []
    for market in sorted(country_metrics):
        row = country_metrics[market]
        row["customers"] = len(row["customers"])
        row["aov_czk"] = round(pct(row["revenue_czk"], row["orders"]), 2)
        row["repeat_order_share"] = round(pct(row["repeat_orders"], row["identified_orders"]), 4)
        row["repeat_revenue_share"] = round(pct(row["repeat_revenue_czk"], row["identified_revenue_czk"]), 4)
        country_rows.append(row)

    segment_rows = [
        {"segment": segment, "customers": count}
        for segment, count in sorted(segments.items(), key=lambda item: (-item[1], item[0]))
    ]
    band_rows = [{"orders_band": band, "customers": count} for band, count in customer_order_bands.items()]
    quality_rows = [{"flag": key, "count": value} for key, value in quality_flags.items()]

    one_timers = sum(1 for stats in customer_stats.values() if stats["orders"] == 1)
    repeat_customers = sum(1 for stats in customer_stats.values() if stats["orders"] >= 2)
    repeat_orders = sum(1 for customer_orders in customers.values() for idx, _ in enumerate(customer_orders) if idx > 0)
    repeat_revenue = sum(
        order.total_czk for customer_orders in customers.values() for idx, order in enumerate(customer_orders) if idx > 0
    )

    topline_revenue = sum(order.total_czk for order in valid_orders)
    identified_revenue = sum(order.total_czk for order in identified_valid)

    h1_2025_cutoff = latest_dt.replace(year=2025)
    h1_2025 = [order for order in valid_orders if datetime(2025, 1, 1) <= order.dt <= h1_2025_cutoff]
    h1_2026 = [order for order in valid_orders if datetime(2026, 1, 1) <= order.dt <= latest_dt]

    def compare_period(newer, older, key):
        newer_value = sum(getattr(order, key) if isinstance(key, str) else key(order) for order in newer)
        older_value = sum(getattr(order, key) if isinstance(key, str) else key(order) for order in older)
        delta = pct(newer_value - older_value, older_value) if older_value else 0.0
        return newer_value, older_value, delta

    h1_orders_2026, h1_orders_2025, h1_orders_delta = compare_period(h1_2026, h1_2025, lambda order: 1)
    h1_revenue_2026, h1_revenue_2025, h1_revenue_delta = compare_period(h1_2026, h1_2025, "total_czk")

    insights = {
        "coverage": {
            "start": orders[0].dt.isoformat(sep=" "),
            "end": latest_dt.isoformat(sep=" "),
            "rows_total": len(orders),
            "years": file_summaries,
        },
        "topline": {
            "valid_orders": len(valid_orders),
            "valid_revenue_czk": round(topline_revenue, 2),
            "anonymous_valid_orders": len(anonymous_valid),
            "anonymous_valid_revenue_czk": round(sum(order.total_czk for order in anonymous_valid), 2),
        },
        "behavior_subset": {
            "identified_orders": len(identified_valid),
            "identified_revenue_czk": round(identified_revenue, 2),
            "identified_customers": len(customers),
            "single_observed_order_customers": one_timers,
            "multi_observed_order_customers": repeat_customers,
            "seen_before_orders": repeat_orders,
            "seen_before_revenue_czk": round(repeat_revenue, 2),
            "multi_observed_order_customer_share": round(pct(repeat_customers, len(customers)), 4),
            "seen_before_order_share": round(pct(repeat_orders, len(identified_valid)), 4),
            "seen_before_revenue_share": round(pct(repeat_revenue, identified_revenue), 4),
        },
        "transitions": transition_rows,
        "segments": segment_rows,
        "countries": [
            {
                "market": row["market"],
                "orders": row["orders"],
                "revenue_czk": round(row["revenue_czk"], 2),
                "identified_orders": row["identified_orders"],
                "identified_revenue_czk": round(row["identified_revenue_czk"], 2),
                "customers": row["customers"],
                "seen_before_orders": row["repeat_orders"],
                "seen_before_revenue_czk": round(row["repeat_revenue_czk"], 2),
                "aov_czk": row["aov_czk"],
                "seen_before_order_share": row["repeat_order_share"],
                "seen_before_revenue_share": row["repeat_revenue_share"],
            }
            for row in country_rows
        ],
        "years": [
            {
                "year": row["year"],
                "valid_orders": row["valid_orders"],
                "valid_revenue_czk": round(row["valid_revenue_czk"], 2),
                "identified_orders": row["identified_orders"],
                "identified_revenue_czk": round(row["identified_revenue_czk"], 2),
                "first_seen_orders": row["new_customer_orders"],
                "seen_before_orders": row["repeat_orders"],
                "first_seen_customers": row["new_customers"],
                "seen_before_order_share": row["repeat_order_share"],
                "seen_before_revenue_share": row["repeat_revenue_share"],
            }
            for row in yearly_rows
        ],
        "data_quality": quality_rows,
        "h1_yoy": {
            "orders_2026": h1_orders_2026,
            "orders_2025": h1_orders_2025,
            "orders_delta": round(h1_orders_delta, 4),
            "revenue_2026": round(h1_revenue_2026, 2),
            "revenue_2025": round(h1_revenue_2025, 2),
            "revenue_delta": round(h1_revenue_delta, 4),
        },
    }

    monthly_export_rows = [
        {
            "month": row["month"],
            "valid_orders": row["valid_orders"],
            "valid_revenue_czk": round(row["valid_revenue_czk"], 2),
            "identified_orders": row["identified_orders"],
            "identified_revenue_czk": round(row["identified_revenue_czk"], 2),
            "first_seen_orders": row["new_customer_orders"],
            "first_seen_revenue_czk": round(row["new_customer_revenue_czk"], 2),
            "seen_before_orders": row["repeat_orders"],
            "seen_before_revenue_czk": round(row["repeat_revenue_czk"], 2),
            "first_seen_customers": row["new_customers"],
            "seen_before_customers": row["repeat_customers"],
            "seen_before_order_share": row["repeat_order_share"],
            "seen_before_revenue_share": row["repeat_revenue_share"],
        }
        for row in monthly_rows
    ]
    country_export_rows = [
        {
            "market": row["market"],
            "orders": row["orders"],
            "revenue_czk": round(row["revenue_czk"], 2),
            "identified_orders": row["identified_orders"],
            "identified_revenue_czk": round(row["identified_revenue_czk"], 2),
            "customers": row["customers"],
            "seen_before_orders": row["repeat_orders"],
            "seen_before_revenue_czk": round(row["repeat_revenue_czk"], 2),
            "aov_czk": row["aov_czk"],
            "seen_before_order_share": row["repeat_order_share"],
            "seen_before_revenue_share": row["repeat_revenue_share"],
        }
        for row in country_rows
    ]
    yearly_export_rows = [
        {
            "year": row["year"],
            "valid_orders": row["valid_orders"],
            "valid_revenue_czk": round(row["valid_revenue_czk"], 2),
            "identified_orders": row["identified_orders"],
            "identified_revenue_czk": round(row["identified_revenue_czk"], 2),
            "first_seen_orders": row["new_customer_orders"],
            "seen_before_orders": row["repeat_orders"],
            "first_seen_customers": row["new_customers"],
            "seen_before_order_share": row["repeat_order_share"],
            "seen_before_revenue_share": row["repeat_revenue_share"],
        }
        for row in yearly_rows
    ]

    write_csv(
        DOCS_DIR / "monthly_metrics.csv",
        monthly_export_rows,
        [
            "month",
            "valid_orders",
            "valid_revenue_czk",
            "identified_orders",
            "identified_revenue_czk",
            "first_seen_orders",
            "first_seen_revenue_czk",
            "seen_before_orders",
            "seen_before_revenue_czk",
            "first_seen_customers",
            "seen_before_customers",
            "seen_before_order_share",
            "seen_before_revenue_share",
        ],
    )
    write_csv(
        DOCS_DIR / "country_metrics.csv",
        country_export_rows,
        [
            "market",
            "orders",
            "revenue_czk",
            "identified_orders",
            "identified_revenue_czk",
            "customers",
            "seen_before_orders",
            "seen_before_revenue_czk",
            "aov_czk",
            "seen_before_order_share",
            "seen_before_revenue_share",
        ],
    )
    write_csv(
        DOCS_DIR / "yearly_metrics.csv",
        yearly_export_rows,
        [
            "year",
            "valid_orders",
            "valid_revenue_czk",
            "identified_orders",
            "identified_revenue_czk",
            "first_seen_orders",
            "seen_before_orders",
            "first_seen_customers",
            "seen_before_order_share",
            "seen_before_revenue_share",
        ],
    )
    write_csv(DOCS_DIR / "segment_summary.csv", segment_rows, ["segment", "customers"])
    write_csv(DOCS_DIR / "customer_order_bands.csv", band_rows, ["orders_band", "customers"])
    write_csv(DOCS_DIR / "data_quality_flags.csv", quality_rows, ["flag", "count"])
    (DOCS_DIR / "summary.json").write_text(json.dumps(insights, ensure_ascii=False, indent=2), encoding="utf-8")

    monthly_revenue_chart = svg_line_chart(
        [{"label": row["month"][2:], "value": row["valid_revenue_czk"]} for row in monthly_rows]
    )
    repeat_share_chart = svg_stacked_share_chart(
        [{"label": row["month"][2:], "repeat_share": row["repeat_order_share"]} for row in monthly_rows]
    )

    transition_lookup = {(row["position"], row["window_days"]): row for row in transition_rows}
    country_lookup = {row["market"]: row for row in country_rows}

    summary_cards = [
        ("Valid orders", f"{len(valid_orders):,}".replace(",", " ")),
        ("Valid revenue", f"{fmt_money(topline_revenue)} Kč"),
        ("Identified customers", f"{len(customers):,}".replace(",", " ")),
        ("Seen-before revenue share", fmt_pct(pct(repeat_revenue, identified_revenue))),
        ("Observed 1→2 in 90d", fmt_pct(transition_lookup[(1, 90)]["rate"])),
        ("Observed 2→3 in 90d", fmt_pct(transition_lookup[(2, 90)]["rate"])),
    ]

    key_findings = [
        f"Zákazníci se 2+ pozorovanými objednávkami tvoří {fmt_pct(pct(repeat_customers, len(customers)))} identifikované báze a nesou {fmt_pct(pct(repeat_revenue, identified_revenue))} identifikovaných tržeb.",
        f"Největší observed monetization opportunity je báze s jedinou pozorovanou objednávkou: {one_timers:,} zákazníků.".replace(",", " "),
        f"Observed rychlost přechodu 1→2 objednávka je do 90 dnů {fmt_pct(transition_lookup[(1, 90)]['rate'])}, 2→3 objednávka do 90 dnů {fmt_pct(transition_lookup[(2, 90)]['rate'])}.",
        f"SK monetizuje výrazně lépe než CZ: AOV {fmt_money2(country_lookup['SK']['aov_czk'])} Kč vs {fmt_money2(country_lookup['CZ']['aov_czk'])} Kč.",
        f"YTD do {latest_dt.strftime('%d.%m. %H:%M')} vs stejný timestamp window 2025: objednávky {fmt_pct(h1_orders_delta)} a tržby {fmt_pct(h1_revenue_delta)}.",
    ]

    monthly_table_rows = []
    for row in monthly_rows:
        monthly_table_rows.append(
            "<tr>"
            f"<td>{row['month']}</td>"
            f"<td>{fmt_money(row['valid_revenue_czk'])} Kč</td>"
            f"<td>{row['valid_orders']}</td>"
            f"<td>{row['new_customers']}</td>"
            f"<td>{fmt_pct(row['repeat_order_share'])}</td>"
            f"<td>{fmt_pct(row['repeat_revenue_share'])}</td>"
            "</tr>"
        )

    country_table_rows = []
    for row in country_rows:
        country_table_rows.append(
            "<tr>"
            f"<td>{row['market']}</td>"
            f"<td>{fmt_money(row['revenue_czk'])} Kč</td>"
            f"<td>{row['orders']}</td>"
            f"<td>{fmt_money2(row['aov_czk'])} Kč</td>"
            f"<td>{fmt_pct(row['repeat_order_share'])}</td>"
            f"<td>{fmt_pct(row['repeat_revenue_share'])}</td>"
            "</tr>"
        )

    segment_table_rows = []
    for row in segment_rows:
        segment_table_rows.append(
            f"<tr><td>{html.escape(row['segment'])}</td><td>{row['customers']}</td></tr>"
        )
    yearly_table_rows = []
    for row in yearly_rows:
        yearly_table_rows.append(
            "<tr>"
            f"<td>{row['year']}</td>"
            f"<td>{fmt_money(row['valid_revenue_czk'])} Kč</td>"
            f"<td>{row['valid_orders']}</td>"
            f"<td>{row['new_customers']}</td>"
            f"<td>{fmt_pct(row['repeat_order_share'])}</td>"
            f"<td>{fmt_pct(row['repeat_revenue_share'])}</td>"
            "</tr>"
        )

    html_report = f"""<!doctype html>
<html lang="cs">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>TianDe Orders 2024–2026 Analysis</title>
  <style>
    :root {{
      --bg: #f4efe7;
      --surface: #fffdf8;
      --line: #e7dccb;
      --ink: #201814;
      --muted: #6d6259;
      --accent: #9a3412;
      --accent-2: #0f766e;
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
    .wrap {{ max-width: 1200px; margin: 0 auto; padding: 28px; }}
    .hero {{
      background: linear-gradient(135deg, rgba(255,255,255,0.86), rgba(246,231,210,0.95));
      border: 1px solid var(--line);
      border-radius: 26px;
      padding: 28px;
      box-shadow: 0 12px 40px rgba(32, 24, 20, 0.06);
    }}
    h1 {{ margin: 0 0 10px; font-size: 42px; line-height: 1.05; }}
    .lede {{ font-size: 18px; line-height: 1.6; max-width: 900px; }}
    .meta {{ color: var(--muted); font-size: 14px; line-height: 1.6; }}
    .cards {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 14px;
      margin: 18px 0 30px;
    }}
    .card, .panel {{
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 22px;
      padding: 20px;
      box-shadow: 0 8px 24px rgba(32, 24, 20, 0.04);
    }}
    .card .kicker {{ font-size: 12px; letter-spacing: .08em; text-transform: uppercase; color: var(--muted); }}
    .card .value {{ margin-top: 8px; font-size: 30px; font-weight: 700; }}
    .grid-2 {{ display: grid; grid-template-columns: 1.4fr 1fr; gap: 18px; margin-top: 18px; }}
    .grid-3 {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 18px; margin-top: 18px; }}
    h2 {{ margin: 0 0 12px; font-size: 26px; }}
    h3 {{ margin: 0 0 10px; font-size: 18px; }}
    ul {{ margin: 0; padding-left: 20px; line-height: 1.7; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
    th, td {{ padding: 10px 8px; border-bottom: 1px solid var(--line); text-align: left; }}
    th {{ font-size: 12px; text-transform: uppercase; letter-spacing: .06em; color: var(--muted); }}
    .pill {{ display:inline-block; padding:6px 10px; border-radius:999px; background:var(--soft); color:var(--accent); font-size:13px; margin:0 8px 8px 0; }}
    .foot {{ color: var(--muted); font-size: 13px; line-height: 1.6; margin-top: 18px; }}
    a {{ color: var(--accent); }}
    @media (max-width: 980px) {{
      .cards, .grid-2, .grid-3 {{ grid-template-columns: 1fr; }}
      h1 {{ font-size: 34px; }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <section class="hero">
      <div class="meta">Zdroj: lokální exporty warehouse order level | Pokrytí: {orders[0].dt.strftime('%d.%m.%Y %H:%M')} až {latest_dt.strftime('%d.%m.%Y %H:%M')} | Aktualizováno: {datetime.now().strftime('%d.%m.%Y %H:%M')}</div>
      <h1>TianDe customer & order deep-dive za 3 roky</h1>
      <div class="lede">Analýza stojí nad samostatnými exporty <strong>2024</strong>, <strong>2025</strong> a <strong>H1 2026</strong>. Neobsahuje raw zákaznická data v repozitáři, jen agregované výstupy, metodiku a závěry, které se dají dál používat pro CRM, management i growth roadmapu.</div>
      <div style="margin-top:16px;">
        <span class="pill">Lifecycle monetization > broad awareness</span>
        <span class="pill">Repeat revenue je hlavní motor</span>
        <span class="pill">CZ má prostor na basket lift</span>
        <span class="pill">SK je referenční monetizační model</span>
      </div>
    </section>

    <section class="cards">
      {''.join(f"<div class='card'><div class='kicker'>{html.escape(label)}</div><div class='value'>{html.escape(value)}</div></div>" for label, value in summary_cards)}
    </section>

    <section class="grid-2">
      <div class="panel">
        <h2>Executive summary</h2>
        <ul>
          {''.join(f"<li>{html.escape(item)}</li>" for item in key_findings)}
        </ul>
        <div class="foot">Top-line pracuje s validními objednávkami: <code>status_id ∈ {{1,3,5}}</code>, <code>order_total_czk &gt; 0</code>, <code>is_counted = true</code>. Customer behavior subset používá identifikovatelné objednávky přes <code>customer_id</code> a tam, kde chybí, dělá bezpečný fallback na email; pokud email vede jednoznačně na jediné <code>customer_id</code>, objednávky se k sobě stitchnou.</div>
      </div>
      <div class="panel">
        <h2>90denní priority</h2>
        <ul>
          <li>Zrychlit 1→2 objednávku přes 0–45denní CRM a replenishment flow.</li>
          <li>Zvednout 2→3 objednávku přes bundle a routine-completion cross-sell.</li>
          <li>Zvlášť chránit VIP aktivní bázi a neředit ji plošnou slevou.</li>
          <li>V CZ zvyšovat AOV přes threshold gift a curated sety, ne přes širší katalog.</li>
          <li>SK vést samostatně jako vyšší-monetizační geosegment s vlastní kreativitou a CRM.</li>
        </ul>
      </div>
    </section>

    <section class="grid-2">
      <div class="panel">
        <h2>Monthly revenue trend</h2>
        {monthly_revenue_chart}
      </div>
      <div class="panel">
        <h2>Seen-before share by month</h2>
        {repeat_share_chart}
        <div class="foot"><span style="color:#059669;">Zelená</span> = objednávky od zákazníků už dříve viděných v datasetu, <span style="color:#f59e0b;">oranžová</span> = první pozorovaná objednávka v dostupném 2024–2026 výřezu.</div>
      </div>
    </section>

    <section class="grid-3">
      <div class="panel">
        <h3>Transition rates</h3>
        <table>
          <thead><tr><th>Observed step</th><th>Window</th><th>Rate</th><th>Eligible</th></tr></thead>
          <tbody>
            {''.join(f"<tr><td>{'1→2' if row['position'] == 1 else '2→3'}</td><td>{row['window_days']} dní</td><td>{fmt_pct(row['rate'])}</td><td>{row['eligible_customers']}</td></tr>" for row in transition_rows)}
          </tbody>
        </table>
      </div>
      <div class="panel">
        <h3>Country lens</h3>
        <table>
          <thead><tr><th>Market</th><th>Revenue</th><th>Orders</th><th>AOV</th><th>Seen-before order share</th><th>Seen-before revenue share</th></tr></thead>
          <tbody>{''.join(country_table_rows)}</tbody>
        </table>
      </div>
      <div class="panel">
        <h3>Lifecycle segments</h3>
        <table>
          <thead><tr><th>Segment</th><th>Customers</th></tr></thead>
          <tbody>{''.join(segment_table_rows[:10])}</tbody>
        </table>
      </div>
    </section>

    <section class="grid-2">
      <div class="panel">
        <h2>Yearly view</h2>
        <table>
          <thead>
            <tr>
              <th>Year</th>
              <th>Revenue</th>
              <th>Orders</th>
              <th>First-seen cust.</th>
              <th>Seen-before order share</th>
              <th>Seen-before revenue share</th>
            </tr>
          </thead>
          <tbody>{''.join(yearly_table_rows)}</tbody>
        </table>
      </div>
      <div class="panel">
        <h2>Recommended action stack</h2>
        <ul>
          <li><strong>0–45 dní po 1. nákupu:</strong> tlačit step-2 doplnění, refill duo a threshold gift místo univerzální slevy.</li>
          <li><strong>46–90 dní po 1. nákupu:</strong> win-back přes curated comeback set, ne přes široký katalog.</li>
          <li><strong>Repeat 2–4 objednávky:</strong> cross-sell do kompletní rutiny, multi-buy a předpřipravené bundle košíky.</li>
          <li><strong>VIP:</strong> early access, dárky za loajalitu, méně discount-first tónu.</li>
          <li><strong>CZ vs SK:</strong> převzít do CZ lepší basket mechanics ze SK a SK nechat jako samostatný CRM a paid stream.</li>
        </ul>
      </div>
    </section>

    <section class="grid-2">
      <div class="panel">
        <h2>Monthly table</h2>
        <table>
          <thead>
            <tr>
              <th>Month</th>
              <th>Revenue</th>
              <th>Orders</th>
              <th>First-seen cust.</th>
              <th>Seen-before order share</th>
              <th>Seen-before revenue share</th>
            </tr>
          </thead>
          <tbody>{''.join(monthly_table_rows)}</tbody>
        </table>
      </div>
      <div class="panel">
        <h2>Data quality & caveats</h2>
        <ul>
          <li>Anonymní validní objednávky nejsou vyhozené z topline, ale nejsou v customer-behavior metrikách.</li>
          <li>`First-seen` a `seen-before` neznamená first-ever vs repeat-ever. Je to jen první vs dříve viděná objednávka v dostupném výřezu 2024–2026, takže 2024 je z principu levostranně oříznutý warm-up rok.</li>
          <li>H1 2026 je jen do <strong>29. 6. 2026 15:44</strong>, takže full-year 2026 srovnání by bylo zavádějící.</li>
          <li><code>items_count</code> je objednávková exportní hodnota, ne garantovaný počet unikátních SKU.</li>
          <li>Repo neobsahuje raw customer exporty ani PII, jen agregace a metodiku.</li>
        </ul>
        <table>
          <thead><tr><th>Flag</th><th>Count</th></tr></thead>
          <tbody>{''.join(f"<tr><td>{html.escape(row['flag'])}</td><td>{row['count']}</td></tr>" for row in quality_rows)}</tbody>
        </table>
      </div>
    </section>

    <section class="panel" style="margin-top:18px;">
      <h2>Downloads</h2>
      <ul>
        <li><a href="./summary.json">summary.json</a></li>
        <li><a href="./monthly_metrics.csv">monthly_metrics.csv</a></li>
        <li><a href="./country_metrics.csv">country_metrics.csv</a></li>
        <li><a href="./yearly_metrics.csv">yearly_metrics.csv</a></li>
        <li><a href="./segment_summary.csv">segment_summary.csv</a></li>
        <li><a href="./customer_order_bands.csv">customer_order_bands.csv</a></li>
        <li><a href="./ceo-one-pager.html">CEO one-pager live</a></li>
        <li><a href="https://github.com/rkonfal/tiande-orders-3y-analysis">GitHub repository</a></li>
      </ul>
    </section>
  </div>
</body>
</html>
"""
    (DOCS_DIR / "index.html").write_text(html_report, encoding="utf-8")

    readme = f"""# TianDe orders 3Y analysis

This repo contains an aggregated deep-dive over TianDe warehouse order exports for:

- 2024-01-01 to 2024-12-31
- 2025-01-01 to 2025-12-31
- 2026-01-01 to 2026-06-29 15:44

## Scope

- `399 364` raw rows across three yearly CSV exports
- valid topline = `status_id in {{1,3,5}}`, `order_total_czk > 0`, `is_counted = true`
- customer behavior subset = identifiable orders via `customer_id`, fallback normalized email, plus unambiguous email-to-id stitching
- note: `new` / `repeat` style fields in generated exports mean `first seen in the 2024-2026 window` vs `seen earlier in the same window`, not guaranteed first-ever vs repeat-ever

## Core findings

- Customers with 2+ observed orders drive the business: {fmt_pct(pct(repeat_customers, len(customers)))} of identified customers generated {fmt_pct(pct(repeat_revenue, identified_revenue))} of identified revenue.
- The largest observed opportunity is the base with a single observed order: {one_timers:,} customers.
- Observed speed to 2nd order within 90 days is {fmt_pct(transition_lookup[(1, 90)]['rate'])}; observed speed to 3rd order within 90 days from the 2nd is {fmt_pct(transition_lookup[(2, 90)]['rate'])}. 
- SK monetizes materially better than CZ on AOV: {fmt_money2(country_lookup['SK']['aov_czk'])} CZK vs {fmt_money2(country_lookup['CZ']['aov_czk'])} CZK.
- YTD to the same final timestamp window as 2026 vs 2025: orders {fmt_pct(h1_orders_delta)}, revenue {fmt_pct(h1_revenue_delta)}.

## Files

- `scripts/build_analysis.py` regenerates all outputs from local source CSVs
- `docs/index.html` is the live report for GitHub Pages
- `docs/*.csv` and `docs/summary.json` contain aggregated exports

## Privacy

Raw order files stay local and are intentionally excluded from git.
"""
    (REPO_ROOT / "README.md").write_text(readme, encoding="utf-8")


if __name__ == "__main__":
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    build_report()
