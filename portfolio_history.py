"""Portfolio value snapshots and performance analytics."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from gate_client import GatePublicClient

from config import DEFAULT_QUOTE

HISTORY_PATH = Path(__file__).resolve().parent / "portfolio_history.json"
SNAPSHOT_MIN_INTERVAL_SEC = 300
MAX_SNAPSHOTS = 5000


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def load_snapshots() -> list[dict[str, Any]]:
    if not HISTORY_PATH.exists():
        return []
    try:
        data = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
        return data.get("snapshots", [])
    except (json.JSONDecodeError, OSError):
        return []


def save_snapshots(snapshots: list[dict[str, Any]]) -> None:
    if len(snapshots) > MAX_SNAPSHOTS:
        snapshots = snapshots[-MAX_SNAPSHOTS:]
    HISTORY_PATH.write_text(
        json.dumps({"snapshots": snapshots}, indent=2),
        encoding="utf-8",
    )


def record_snapshot(total_value: float, quote: str | None = None) -> None:
    """Append a portfolio total snapshot (throttled)."""
    if total_value <= 0:
        return
    q = (quote or DEFAULT_QUOTE).upper()
    snapshots = load_snapshots()
    now = _now()
    if snapshots:
        last = snapshots[-1]
        try:
            last_ts = datetime.fromisoformat(last["ts"])
            if last_ts.tzinfo is None:
                last_ts = last_ts.replace(tzinfo=timezone.utc)
            if (now - last_ts).total_seconds() < SNAPSHOT_MIN_INTERVAL_SEC:
                if last.get("quote") == q:
                    last_val = float(last.get("total_value", 0))
                    if last_val > 0 and abs(total_value - last_val) / last_val < 0.001:
                        return
        except (ValueError, TypeError):
            pass
    snapshots.append(
        {
            "ts": now.isoformat(),
            "total_value": f"{total_value:.8f}".rstrip("0").rstrip("."),
            "quote": q,
        }
    )
    save_snapshots(snapshots)


def _parse_ts(raw: str) -> datetime:
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def estimate_value_at_day_start(assets: list[dict[str, Any]]) -> float | None:
    """Estimate portfolio value ~24h ago using per-asset 24h % change."""
    total = 0.0
    has_data = False
    for a in assets:
        val = float(a.get("value_quote") or 0)
        if val <= 0:
            continue
        ch = a.get("change_pct")
        if ch is None or ch == "":
            total += val
            continue
        try:
            pct = float(ch)
            start_val = val / (1 + pct / 100.0) if pct != -100 else val
            total += start_val
            has_data = True
        except (TypeError, ValueError):
            total += val
    return total if has_data or total > 0 else None


def find_snapshot_near(snapshots: list[dict], target: datetime, quote: str) -> dict | None:
    best: dict | None = None
    best_delta = None
    for s in snapshots:
        if s.get("quote") != quote:
            continue
        try:
            ts = _parse_ts(s["ts"])
            delta = abs((ts - target).total_seconds())
            if best_delta is None or delta < best_delta:
                best_delta = delta
                best = s
        except (ValueError, TypeError, KeyError):
            continue
    if best_delta is not None and best_delta > 86400 * 2:
        return None
    return best


def _synthetic_value_chart(
    current_value: float, change_pct: str | None, points: int = 24
) -> list[dict[str, Any]]:
    """Flat or ramp chart when live candle data is unavailable."""
    if current_value <= 0:
        return []
    try:
        pct = float(change_pct or 0)
        start = current_value / (1 + pct / 100.0) if pct != -100 else current_value
    except (TypeError, ValueError):
        start = current_value
    chart: list[dict[str, Any]] = []
    for i in range(points):
        t = i / max(points - 1, 1)
        val = start + (current_value - start) * t
        chart.append({"ts": i, "value": f"{val:.4f}".rstrip("0").rstrip(".")})
    return chart


def _synthetic_price_chart(
    current_price: float, change_pct: str | None, points: int = 24
) -> list[dict[str, Any]]:
    """Estimated price ramp when candle data is unavailable."""
    if current_price <= 0:
        return []
    try:
        pct = float(change_pct or 0)
        start = current_price / (1 + pct / 100.0) if pct != -100 else current_price
    except (TypeError, ValueError):
        start = current_price
    chart: list[dict[str, Any]] = []
    for i in range(points):
        t = i / max(points - 1, 1)
        price = start + (current_price - start) * t
        chart.append({"ts": i, "value": f"{price:.8f}".rstrip("0").rstrip(".")})
    return chart


def _fmt_num(val: float, decimals: int = 4) -> str:
    return f"{val:.{decimals}f}".rstrip("0").rstrip(".")


def build_coin_analysis(
    asset: dict[str, Any],
    quote: str,
    public: Any,
    portfolio_total: float | None = None,
) -> dict[str, Any]:
    """Full per-coin analysis: holdings, 24h range, price & value charts."""
    currency = (asset.get("currency") or "").upper()
    q = quote.upper()
    holdings = float(asset.get("total") or 0)
    value = float(asset.get("value_quote") or 0)
    change_pct = asset.get("change_pct")
    pair = asset.get("pair") or public.pair(currency, q)
    price = float(asset.get("price") or 0) if asset.get("price") else None

    price_chart: list[dict[str, Any]] = []
    value_chart: list[dict[str, Any]] = []
    day_high_price: float | None = None
    day_low_price: float | None = None
    chart_source = "live"

    if currency == q:
        price = 1.0
        day_high_price = 1.0
        day_low_price = 1.0
        price_chart = [{"ts": i, "value": "1"} for i in range(24)]
        value_chart = _synthetic_value_chart(value, "0", 24)
        chart_source = "stable"
    else:
        candles = public.get_candle_history(pair, interval="1h", limit=24)
        if candles:
            for c in candles:
                close = c["close"]
                price_chart.append({"ts": c["ts"], "value": _fmt_num(close, 8)})
                if holdings > 0:
                    val = holdings * close
                    value_chart.append({"ts": c["ts"], "value": _fmt_num(val, 4)})
            day_high_price = max(c["high"] for c in candles)
            day_low_price = min(c["low"] for c in candles)
        else:
            chart_source = "estimated"
            if price is None:
                try:
                    ticker = public.get_ticker(pair)
                    price = float(ticker.get("last") or 0)
                    change_pct = change_pct or ticker.get("change_pct")
                except (ValueError, TypeError):
                    price = 0.0
            price_chart = _synthetic_price_chart(price or 0, change_pct, 24)
            value_chart = _synthetic_value_chart(value, change_pct, 24)
            if price and price > 0:
                try:
                    pct = float(change_pct or 0)
                    start_p = price / (1 + pct / 100.0) if pct != -100 else price
                    day_high_price = max(price, start_p)
                    day_low_price = min(price, start_p)
                except (TypeError, ValueError):
                    day_high_price = price
                    day_low_price = price

    high_24h = asset.get("high_24h")
    low_24h = asset.get("low_24h")
    if high_24h is None and day_high_price is not None:
        high_24h = _fmt_num(day_high_price, 8)
    if low_24h is None and day_low_price is not None:
        low_24h = _fmt_num(day_low_price, 8)

    value_high = asset.get("value_high_24h")
    value_low = asset.get("value_low_24h")
    if holdings > 0 and high_24h and low_24h:
        try:
            value_high = _fmt_num(holdings * float(high_24h), 4)
            value_low = _fmt_num(holdings * float(low_24h), 4)
        except (TypeError, ValueError):
            pass
    elif value_chart:
        vals = [float(p["value"]) for p in value_chart]
        value_high = _fmt_num(max(vals), 4)
        value_low = _fmt_num(min(vals), 4)

    est_value_24h: float | None = None
    if value > 0:
        if change_pct:
            try:
                pct = float(change_pct)
                est_value_24h = value / (1 + pct / 100.0) if pct != -100 else value
            except (TypeError, ValueError):
                est_value_24h = None
        if est_value_24h is None and value_chart:
            est_value_24h = float(value_chart[0]["value"])

    vs_24h: dict[str, Any] = {"available": False}
    if est_value_24h is not None and est_value_24h > 0 and value > 0:
        ch = value - est_value_24h
        pct = (ch / est_value_24h) * 100
        vs_24h = {
            "from_value": _fmt_num(est_value_24h, 4),
            "change": _fmt_num(ch, 4),
            "change_pct": f"{pct:.2f}",
            "available": True,
        }

    alloc_pct = asset.get("allocation_pct")
    if portfolio_total and portfolio_total > 0 and value > 0 and not alloc_pct:
        alloc_pct = f"{(value / portfolio_total * 100):.2f}"

    # Fresh ticker for bid/ask/volume
    quote_volume = None
    highest_bid = None
    lowest_ask = None
    if currency != q:
        try:
            ticker = public.get_ticker(pair)
            quote_volume = ticker.get("quote_volume")
            highest_bid = ticker.get("highest_bid")
            lowest_ask = ticker.get("lowest_ask")
            if not change_pct:
                change_pct = ticker.get("change_pct")
            if not high_24h:
                high_24h = ticker.get("high_24h")
            if not low_24h:
                low_24h = ticker.get("low_24h")
        except (ValueError, TypeError):
            pass

    return {
        "coin": currency,
        "pair": pair,
        "quote": q,
        "available": asset.get("available"),
        "locked": asset.get("locked"),
        "total": asset.get("total"),
        "price": asset.get("price") or (_fmt_num(price, 8) if price else None),
        "value_quote": asset.get("value_quote"),
        "allocation_pct": alloc_pct,
        "change_pct": change_pct,
        "high_24h": high_24h,
        "low_24h": low_24h,
        "value_high_24h": value_high,
        "value_low_24h": value_low,
        "highest_bid": highest_bid,
        "lowest_ask": lowest_ask,
        "quote_volume": quote_volume,
        "chart_source": chart_source,
        "price_chart": price_chart,
        "value_chart": value_chart,
        "vs_24h": vs_24h,
        "day": {
            "high_price": _fmt_num(day_high_price, 8) if day_high_price else high_24h,
            "low_price": _fmt_num(day_low_price, 8) if day_low_price else low_24h,
            "high_value": value_high,
            "low_value": value_low,
            "current_value": asset.get("value_quote"),
        },
    }


def build_top_asset_charts(
    assets: list[dict[str, Any]],
    quote: str,
    public: Any,
    top_n: int = 5,
) -> list[dict[str, Any]]:
    """Hourly holding-value charts for top portfolio assets."""
    q = quote.upper()
    ranked = sorted(
        assets,
        key=lambda a: float(a.get("value_quote") or 0),
        reverse=True,
    )
    top = [a for a in ranked if float(a.get("value_quote") or 0) > 0][:top_n]
    charts: list[dict[str, Any]] = []

    for a in top:
        currency = a.get("currency", "")
        value = float(a.get("value_quote") or 0)
        holdings = float(a.get("total") or 0)
        pair = a.get("pair") or public.pair(currency, q)
        change_pct = a.get("change_pct")

        value_points: list[dict[str, Any]] = []
        if currency == q:
            value_points = _synthetic_value_chart(value, "0", 24)
        else:
            prices = public.get_price_history(pair, interval="1h", limit=24)
            if prices and holdings > 0:
                for pt in prices:
                    val = holdings * float(pt["price"])
                    value_points.append(
                        {
                            "ts": pt["ts"],
                            "value": f"{val:.4f}".rstrip("0").rstrip("."),
                        }
                    )
            else:
                value_points = _synthetic_value_chart(value, change_pct, 24)

        if not value_points:
            continue

        vals = [float(p["value"]) for p in value_points]
        charts.append(
            {
                "coin": currency,
                "pair": pair,
                "holdings": a.get("total"),
                "value_quote": a.get("value_quote"),
                "allocation_pct": a.get("allocation_pct"),
                "change_pct": change_pct,
                "chart": value_points,
                "high_value": f"{max(vals):.4f}".rstrip("0").rstrip("."),
                "low_value": f"{min(vals):.4f}".rstrip("0").rstrip("."),
            }
        )
    return charts


def _aggregate_value_charts(series_list: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Sum holding-value series by aligned index (hourly candles)."""
    if not series_list:
        return []
    max_len = max(len(s) for s in series_list)
    merged: list[dict[str, Any]] = []
    for i in range(max_len):
        total = 0.0
        ts: Any = i
        for s in series_list:
            if i >= len(s):
                continue
            pt = s[i]
            total += float(pt.get("value") or 0)
            if pt.get("ts") is not None:
                ts = pt["ts"]
        merged.append({"ts": ts, "value": _fmt_num(total, 4)})
    return merged


def build_group_analysis(
    group: dict[str, Any],
    holdings: list[dict[str, Any]],
    public: Any,
) -> dict[str, Any]:
    """Aggregate analysis for a coin group: total value, chart, per-coin breakdown."""
    q = (group.get("quote") or DEFAULT_QUOTE).upper()
    holdings_map = {h.get("coin", "").upper(): h for h in holdings}
    coins = group.get("coins") or []

    total_value = sum(float(h.get("value_quote") or 0) for h in holdings)
    holdings_count = sum(1 for h in holdings if float(h.get("total") or 0) > 0)

    assets: list[dict[str, Any]] = []
    coins_breakdown: list[dict[str, Any]] = []
    value_series: list[list[dict[str, Any]]] = []

    for coin in coins:
        h = holdings_map.get(coin.upper(), {})
        val = float(h.get("value_quote") or 0)
        total_bal = float(h.get("total") or 0)
        alloc_pct = f"{(val / total_value * 100):.2f}" if total_value > 0 and val > 0 else "0"

        assets.append(
            {
                "currency": coin,
                "total": h.get("total") or "0",
                "value_quote": h.get("value_quote") or "0",
                "allocation_pct": alloc_pct,
                "change_pct": h.get("change_pct"),
                "pair": h.get("pair") or public.pair(coin, q),
            }
        )

        coins_breakdown.append(
            {
                "coin": coin,
                "total": h.get("total") or "0",
                "available": h.get("available") or "0",
                "value_quote": h.get("value_quote"),
                "allocation_pct": alloc_pct,
                "change_pct": h.get("change_pct"),
                "last": h.get("last"),
                "has_balance": total_bal > 0,
            }
        )

        if total_bal <= 0:
            continue

        if coin.upper() == q:
            value_series.append(_synthetic_value_chart(total_bal, "0", 24))
            continue

        pair = h.get("pair") or public.pair(coin, q)
        candles = public.get_candle_history(pair, interval="1h", limit=24)
        if candles:
            pts = [
                {"ts": c["ts"], "value": _fmt_num(total_bal * c["close"], 4)}
                for c in candles
            ]
            value_series.append(pts)
        else:
            value_series.append(
                _synthetic_value_chart(val, h.get("change_pct"), 24)
            )

    chart = _aggregate_value_charts(value_series)
    if len(chart) < 2 and total_value > 0:
        chart = _synthetic_value_chart(total_value, None, 24)
        est = estimate_value_at_day_start(assets)
        if est and est > 0:
            try:
                pct = ((total_value - est) / est) * 100
                for i, pt in enumerate(chart):
                    t = i / max(len(chart) - 1, 1)
                    v = est + (total_value - est) * t
                    pt["value"] = _fmt_num(v, 4)
            except (TypeError, ValueError):
                pass

    est_24h = estimate_value_at_day_start(assets)
    vs_24h: dict[str, Any] = {"available": False}
    if est_24h is not None and est_24h > 0 and total_value > 0:
        ch = total_value - est_24h
        pct = (ch / est_24h) * 100
        vs_24h = {
            "from_value": _fmt_num(est_24h, 4),
            "change": _fmt_num(ch, 4),
            "change_pct": f"{pct:.2f}",
            "available": True,
        }

    chart_vals = [float(p["value"]) for p in chart] if chart else []
    day_high = max(chart_vals) if chart_vals else total_value
    day_low = min(chart_vals) if chart_vals else total_value

    top_n = min(8, len(coins))
    top_assets = build_top_asset_charts(assets, q, public, top_n=top_n) if public else []

    return {
        "group_id": group.get("id"),
        "group_name": group.get("name"),
        "quote": q,
        "coins": coins,
        "coins_count": len(coins),
        "holdings_count": holdings_count,
        "current_value": _fmt_num(total_value, 4),
        "allocations": group.get("allocations") or {},
        "vs_24h": vs_24h,
        "day": {
            "high_value": _fmt_num(day_high, 4),
            "low_value": _fmt_num(day_low, 4),
            "current_value": _fmt_num(total_value, 4),
        },
        "chart": chart,
        "top_assets": top_assets,
        "coins_breakdown": coins_breakdown,
    }


def build_analytics(
    current_value: float,
    quote: str,
    assets: list[dict[str, Any]],
    snapshots: list[dict[str, Any]] | None = None,
    public: Any | None = None,
) -> dict[str, Any]:
    snapshots = snapshots or load_snapshots()
    q = quote.upper()
    now = _now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_ago_target = now - timedelta(days=7)
    day_ago_target = now - timedelta(days=1)

    today_vals: list[tuple[datetime, float]] = []
    all_vals: list[tuple[datetime, float]] = []

    for s in snapshots:
        if s.get("quote") != q:
            continue
        try:
            ts = _parse_ts(s["ts"])
            val = float(s["total_value"])
            all_vals.append((ts, val))
            if ts >= today_start:
                today_vals.append((ts, val))
        except (ValueError, TypeError, KeyError):
            continue

    today_vals.append((now, current_value))
    all_vals.append((now, current_value))

    est_day_start = estimate_value_at_day_start(assets)

    day_start_val: float | None = None
    day_start_source = "estimated"
    if today_vals:
        first_today = min(today_vals, key=lambda x: x[0])
        if first_today[0] <= today_start + timedelta(minutes=30):
            day_start_val = first_today[1]
            day_start_source = "snapshot"
        elif today_vals:
            day_start_val = today_vals[0][1]
            day_start_source = "snapshot_first_today"

    if day_start_val is None and est_day_start is not None:
        day_start_val = est_day_start
        day_start_source = "estimated_24h"

    day_end_val = current_value
    day_high = max(v for _, v in today_vals) if today_vals else current_value
    day_low = min(v for _, v in today_vals) if today_vals else current_value

    week_snap = find_snapshot_near(
        [s for s in snapshots if s.get("quote") == q],
        week_ago_target,
        q,
    )
    day_snap = find_snapshot_near(
        [s for s in snapshots if s.get("quote") == q],
        day_ago_target,
        q,
    )

    week_ago_val = float(week_snap["total_value"]) if week_snap else None
    day_ago_val = float(day_snap["total_value"]) if day_snap else None

    if day_ago_val is None and est_day_start is not None:
        day_ago_val = est_day_start

    def _change(from_val: float | None) -> dict[str, Any]:
        if from_val is None or from_val <= 0:
            return {"from_value": None, "change": None, "change_pct": None, "available": False}
        ch = current_value - from_val
        pct = (ch / from_val) * 100
        return {
            "from_value": f"{from_val:.4f}".rstrip("0").rstrip("."),
            "change": f"{ch:.4f}".rstrip("0").rstrip("."),
            "change_pct": f"{pct:.2f}",
            "available": True,
        }

    chart_points = sorted(all_vals, key=lambda x: x[0])
    if len(chart_points) > 200:
        step = max(1, len(chart_points) // 200)
        chart_points = chart_points[-200 * step :: step]

    return {
        "quote": q,
        "current_value": f"{current_value:.4f}".rstrip("0").rstrip("."),
        "day": {
            "start_value": (
                f"{day_start_val:.4f}".rstrip("0").rstrip(".") if day_start_val else None
            ),
            "start_source": day_start_source,
            "end_value": f"{day_end_val:.4f}".rstrip("0").rstrip("."),
            "high_value": f"{day_high:.4f}".rstrip("0").rstrip("."),
            "low_value": f"{day_low:.4f}".rstrip("0").rstrip("."),
            "current_value": f"{current_value:.4f}".rstrip("0").rstrip("."),
        },
        "vs_yesterday": _change(day_ago_val),
        "vs_week_ago": _change(week_ago_val),
        "chart": [
            {"ts": ts.isoformat(), "value": f"{v:.4f}".rstrip("0").rstrip(".")}
            for ts, v in chart_points
        ],
        "snapshot_count": len([s for s in snapshots if s.get("quote") == q]),
        "top_assets": build_top_asset_charts(assets, q, public) if public else [],
    }
