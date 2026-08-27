"""Coin groups — create, buy (equal split), and sell."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import DEFAULT_QUOTE
from gate_client import GateClient
from trader import TradeRequest, Trader, summarize_order_results

GROUPS_PATH = Path(__file__).resolve().parent / "groups.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_coin(coin: str) -> str:
    return coin.strip().upper().split("_")[0]


def _fmt_amount(value: float, decimals: int = 8) -> str:
    return f"{value:.{decimals}f}".rstrip("0").rstrip(".")


def load_groups() -> list[dict[str, Any]]:
    if not GROUPS_PATH.exists():
        return []
    try:
        data = json.loads(GROUPS_PATH.read_text(encoding="utf-8"))
        groups = data.get("groups", [])
        for g in groups:
            if "allocations" not in g:
                g["allocations"] = {c: "" for c in g.get("coins", [])}
        return groups
    except (json.JSONDecodeError, OSError):
        return []


def save_groups(groups: list[dict[str, Any]]) -> None:
    GROUPS_PATH.write_text(json.dumps({"groups": groups}, indent=2), encoding="utf-8")


def create_group(
    name: str,
    coins: list[str],
    quote: str | None = None,
    allocations: dict[str, str] | None = None,
) -> dict[str, Any]:
    name = name.strip()
    if not name:
        raise ValueError("Group name is required")

    normalized: list[str] = []
    seen: set[str] = set()
    for c in coins:
        sym = _normalize_coin(c)
        if sym and sym not in seen:
            seen.add(sym)
            normalized.append(sym)

    if not normalized:
        raise ValueError("Select at least one coin for the group")

    alloc_map = _normalize_allocations(normalized, allocations or {})

    group = {
        "id": uuid.uuid4().hex[:12],
        "name": name,
        "coins": normalized,
        "allocations": alloc_map,
        "quote": (quote or DEFAULT_QUOTE).upper(),
        "created_at": _now(),
        "updated_at": _now(),
    }
    groups = load_groups()
    groups.append(group)
    save_groups(groups)
    return group


def update_group_allocations(group_id: str, allocations: dict[str, str]) -> dict[str, Any]:
    group = get_group(group_id)
    if not group:
        raise ValueError("Group not found")

    alloc_map = _normalize_allocations(group["coins"], allocations)
    group["allocations"] = alloc_map
    group["updated_at"] = _now()

    groups = load_groups()
    for i, g in enumerate(groups):
        if g["id"] == group_id:
            groups[i] = group
            break
    save_groups(groups)
    return group


def update_group_coins(group_id: str, coins: list[str]) -> dict[str, Any]:
    """Replace the coin watchlist for a group (preserves allocations for kept coins)."""
    group = get_group(group_id)
    if not group:
        raise ValueError("Group not found")

    normalized: list[str] = []
    seen: set[str] = set()
    for c in coins:
        sym = _normalize_coin(c)
        if sym and sym not in seen:
            seen.add(sym)
            normalized.append(sym)

    if not normalized:
        raise ValueError("Select at least one coin for the group")

    old_allocs = group.get("allocations") or {}
    new_allocs: dict[str, str] = {}
    for coin in normalized:
        new_allocs[coin] = old_allocs.get(coin, "")

    group["coins"] = normalized
    group["allocations"] = _normalize_allocations(normalized, new_allocs)
    group["updated_at"] = _now()

    groups = load_groups()
    for i, g in enumerate(groups):
        if g["id"] == group_id:
            groups[i] = group
            break
    save_groups(groups)
    return group


def _normalize_allocations(coins: list[str], allocations: dict[str, str]) -> dict[str, str]:
    """Map coin -> percentage string; only coins in the group; empty string = auto/equal remainder."""
    result: dict[str, str] = {}
    for coin in coins:
        raw = allocations.get(coin) or allocations.get(coin.upper()) or ""
        s = str(raw).strip()
        if not s:
            result[coin] = ""
            continue
        pct = float(s)
        if pct < 0 or pct > 100:
            raise ValueError(f"Allocation for {coin} must be between 0 and 100")
        result[coin] = f"{pct:.4f}".rstrip("0").rstrip(".")
    explicit_sum = sum(float(v) for v in result.values() if v)
    if explicit_sum > 100:
        raise ValueError(f"Allocations sum to {explicit_sum}% — maximum is 100%")
    return result


def compute_buy_amounts(
    total: float,
    coins: list[str],
    allocations: dict[str, str] | None = None,
) -> dict[str, Any]:
    """
    Split total quote amount across coins.

    - Coins with a set % receive that share of the total (e.g. 75 → 75% of funds).
    - The remaining % is split equally among coins without a set %.
    - If no allocations are set, split equally across all coins.
    """
    if total <= 0:
        raise ValueError("Total amount must be greater than zero")
    if not coins:
        raise ValueError("No coins in group")

    allocs = allocations or {}
    explicit: dict[str, float] = {}
    for coin in coins:
        raw = (allocs.get(coin) or "").strip()
        if raw:
            explicit[coin] = float(raw)

    explicit_sum = sum(explicit.values())
    if explicit_sum > 100:
        raise ValueError(f"Allocations sum to {explicit_sum}% — must be ≤ 100%")

    # No explicit allocations → equal split
    if not explicit:
        per = total / len(coins)
        split = {c: per for c in coins}
        mode = "equal"
    else:
        unset = [c for c in coins if c not in explicit]
        remainder_pct = 100.0 - explicit_sum
        remainder_total = total * remainder_pct / 100.0 if remainder_pct > 0 else 0.0

        split: dict[str, float] = {}
        for coin, pct in explicit.items():
            split[coin] = total * pct / 100.0 if pct > 0 else 0.0

        if remainder_pct > 0 and unset:
            per = remainder_total / len(unset)
            for coin in unset:
                split[coin] = per
        else:
            for coin in unset:
                split[coin] = 0.0

        if not unset:
            mode = "percent_full"
        elif remainder_pct > 0:
            mode = "percent"
        else:
            mode = "percent_full"

    amounts: dict[str, str] = {}
    breakdown: list[dict[str, Any]] = []
    unset_count = len([c for c in coins if c not in explicit]) if explicit else 0
    per_auto_pct = (
        (100.0 - explicit_sum) / unset_count
        if unset_count and explicit and (100.0 - explicit_sum) > 0
        else None
    )
    active_count = sum(1 for c in coins if split.get(c, 0.0) > 0)
    if active_count == 0:
        raise ValueError("No coins to buy — check allocations")

    for coin in coins:
        amt = split.get(coin, 0.0)
        if amt > 0:
            amt_str = f"{amt:.8f}".rstrip("0").rstrip(".")
            amounts[coin] = amt_str
            pct_of_total = (amt / total * 100) if total > 0 else 0

            if mode == "equal":
                rule = "equal"
                rule_text = f"Equal split ({100 / len(coins):.2f}% each)"
            elif coin in explicit:
                rule = "fixed"
                rule_text = f"You set {explicit[coin]:g}%"
            else:
                rule = "auto"
                auto_pct = per_auto_pct or 0
                rule_text = f"Auto — {auto_pct:.2f}% each ({remainder_pct:.0f}% ÷ {unset_count} coins)"

            breakdown.append(
                {
                    "coin": coin,
                    "amount": amt_str,
                    "pct_of_total": f"{pct_of_total:.2f}",
                    "allocation_pct": explicit.get(coin) if coin in explicit else None,
                    "rule": rule,
                    "rule_text": rule_text,
                    "included": True,
                }
            )
        else:
            if coin in explicit and explicit.get(coin, 0) == 0:
                skip_reason = "Set to 0% — not included in buy"
            elif remainder_pct == 0 and coin not in explicit:
                skip_reason = "100% allocated to other coins — not included"
            else:
                skip_reason = "No allocation — not included"
            breakdown.append(
                {
                    "coin": coin,
                    "amount": "0",
                    "pct_of_total": "0.00",
                    "allocation_pct": explicit.get(coin) if coin in explicit else None,
                    "rule": "skipped",
                    "rule_text": skip_reason,
                    "included": False,
                }
            )

    summary_text = ""
    if mode == "equal":
        summary_text = f"Equal split — each coin gets {100 / len(coins):.2f}% of the buy total"
    elif mode == "percent_full" and unset_count and remainder_pct == 0:
        included = [c for c in coins if split.get(c, 0) > 0]
        parts = [f"{c} {explicit[c]:g}%" for c in included if c in explicit]
        summary_text = (
            f"100% allocated — {', '.join(parts)} only "
            f"({active_count} of {len(coins)} coins)"
        )
    elif mode == "percent_full":
        summary_text = (
            f"100% across all coins — each gets its set % of the buy total"
        )
    else:
        fixed_parts = [
            f"{c} {explicit[c]:g}%"
            for c in coins
            if c in explicit
        ]
        summary_text = (
            f"{', '.join(fixed_parts)} · "
            f"remaining {remainder_pct:.0f}% split equally among {unset_count} auto coin(s)"
        )

    return {
        "mode": mode,
        "total_amount": str(total),
        "explicit_sum_pct": f"{explicit_sum:.2f}" if explicit else "0",
        "remainder_pct": f"{(100 - explicit_sum):.2f}" if explicit else "100",
        "unset_count": unset_count,
        "per_auto_pct": f"{per_auto_pct:.2f}" if per_auto_pct is not None else None,
        "summary_text": summary_text,
        "amounts": amounts,
        "breakdown": breakdown,
    }


def delete_group(group_id: str) -> bool:
    groups = load_groups()
    new_groups = [g for g in groups if g["id"] != group_id]
    if len(new_groups) == len(groups):
        return False
    save_groups(new_groups)
    return True


def get_group(group_id: str) -> dict[str, Any] | None:
    return next((g for g in load_groups() if g["id"] == group_id), None)


class GroupTrader:
    def __init__(self, client: GateClient | None = None) -> None:
        self.client = client or GateClient()
        self.trader = Trader(self.client)

    def list_groups_with_holdings(self) -> list[dict[str, Any]]:
        groups = load_groups()
        result: list[dict[str, Any]] = []
        for g in groups:
            holdings = self.client.get_group_holdings(g["coins"], g.get("quote"))
            total_value = sum(float(h["value_quote"] or 0) for h in holdings)
            result.append(
                {
                    **g,
                    "holdings": holdings,
                    "holdings_count": sum(1 for h in holdings if float(h["total"]) > 0),
                    "total_value": f"{total_value:.4f}".rstrip("0").rstrip("."),
                }
            )
        return result

    def buy_group(self, group_id: str, total_amount: str) -> dict[str, Any]:
        group = get_group(group_id)
        if not group:
            raise ValueError("Group not found")

        total = float(total_amount)
        coins = group["coins"]
        quote = group.get("quote") or DEFAULT_QUOTE
        allocations = group.get("allocations") or {}

        split = compute_buy_amounts(total, coins, allocations)
        amounts = split["amounts"]

        self.client.warm_pair_cache(coins, quote)
        issues = self.client.validate_buy_amounts(
            amounts, quote, check_ticker=True
        )
        if issues:
            raise ValueError(
                "Cannot buy — fix these issues first:\n" + "\n".join(f"• {i}" for i in issues)
            )

        requests = [
            TradeRequest(
                coin=coin,
                amount=amounts[coin],
                side="buy",
                order_type="market",
                quote=quote,
            )
            for coin in coins
            if coin in amounts and float(amounts[coin]) > 0
        ]
        if not requests:
            raise ValueError("No coins to buy — check allocations")
        results = self.trader.buy_multiple(requests)
        execution = summarize_order_results(results)
        if execution["failed_count"] > 0:
            raise ValueError(execution["message"])

        return {
            "group_id": group_id,
            "group_name": group["name"],
            "action": "buy",
            "total_amount": str(total_amount),
            "quote": quote,
            "coins": coins,
            "allocations": allocations,
            "split": split,
            "execution": execution,
            "results": results,
        }

    def preview_buy(self, group_id: str, total_amount: str) -> dict[str, Any]:
        group = get_group(group_id)
        if not group:
            raise ValueError("Group not found")
        total = float(total_amount)
        quote = group.get("quote") or DEFAULT_QUOTE
        split = compute_buy_amounts(total, group["coins"], group.get("allocations") or {})
        self.client.warm_pair_cache(group["coins"], quote)
        balances = {
            b["currency"]: b for b in self.client.list_balances(include_zero=False)
        }
        tickers = self.client._public.get_tickers_for_coins(group["coins"], quote)
        quote_row = balances.get(quote)
        quote_available = float(quote_row["available"]) if quote_row else 0.0

        for row in split["breakdown"]:
            sym = row["coin"]
            coin_row = balances.get(sym)
            current = float(coin_row["available"]) if coin_row else 0.0
            row["current_balance"] = coin_row["available"] if coin_row else "0"

            if not row.get("included"):
                row["balance_after"] = row["current_balance"]
                continue

            market = tickers.get(sym)
            price = float(market["last"]) if market and market.get("last") else None
            spend = float(row["amount"])
            row["price"] = market.get("last") if market else None
            if price and price > 0:
                est_coin = spend / price
                row["est_coin_amount"] = _fmt_amount(est_coin)
                row["balance_after"] = _fmt_amount(current + est_coin)
            else:
                row["est_coin_amount"] = None
                row["balance_after"] = row["current_balance"]

        issues = self.client.validate_buy_amounts(
            split["amounts"], quote, check_ticker=True
        )
        if total > quote_available:
            issues.append(
                f"Insufficient {quote} balance — need {total:.2f}, have {quote_available:.2f}"
            )
        min_quote = 3.0
        for coin in split["amounts"]:
            try:
                min_quote = max(
                    min_quote, self.client.get_pair_info(coin, quote)["min_quote_amount"]
                )
            except ValueError:
                pass
        quote_after = quote_available - total
        return {
            "group_id": group_id,
            "group_name": group["name"],
            "quote": quote,
            "allocations": group.get("allocations") or {},
            "quote_balance": _fmt_amount(quote_available, 4),
            "quote_balance_after": _fmt_amount(quote_after, 4),
            "issues": issues,
            "can_buy": len(issues) == 0,
            "min_order_quote": f"{min_quote:g}",
            **split,
        }

    def buy_group_equal(self, group_id: str, total_amount: str) -> dict[str, Any]:
        """Legacy equal split — use buy_group instead."""
        return self.buy_group(group_id, total_amount)

    def preview_sell(
        self,
        group_id: str,
        coins: list[str] | None = None,
        amounts: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        group = get_group(group_id)
        if not group:
            raise ValueError("Group not found")

        quote = group.get("quote") or DEFAULT_QUOTE
        holdings = self.client.get_group_holdings(group["coins"], quote)
        balances = {b["currency"]: b for b in self.client.list_balances(include_zero=False)}
        quote_row = balances.get(quote)
        quote_available = float(quote_row["available"]) if quote_row else 0.0
        selected = {_normalize_coin(c) for c in (coins or [])} if coins else None

        breakdown: list[dict[str, Any]] = []
        total_value = 0.0
        issues: list[str] = []

        for h in holdings:
            sym = h["coin"]
            if selected is not None and sym not in selected:
                continue
            row = balances.get(sym)
            available = float(row["available"]) if row else 0.0
            if available <= 0:
                if selected is not None and sym in selected:
                    issues.append(f"{sym}: no available balance to sell")
                continue

            if amounts and amounts.get(sym):
                sell_amt = float(str(amounts[sym]).strip())
                if sell_amt <= 0:
                    issues.append(f"{sym}: amount must be greater than zero")
                    continue
                if sell_amt > available:
                    issues.append(f"{sym}: cannot sell {sell_amt}; only {available} available")
                    continue
                sell_str = f"{sell_amt:.8f}".rstrip("0").rstrip(".")
            else:
                sell_str = row["available"]
                sell_amt = available

            price = float(h["last"] or 0) if h.get("last") else 0
            est_value = sell_amt * price if price > 0 else None
            if est_value:
                total_value += est_value

            breakdown.append(
                {
                    "coin": sym,
                    "pair": h["pair"],
                    "amount": sell_str,
                    "available": row["available"],
                    "current_balance": row["available"],
                    "balance_after": _fmt_amount(available - sell_amt),
                    "price": h.get("last"),
                    "est_value_quote": (
                        f"{est_value:.4f}".rstrip("0").rstrip(".") if est_value else None
                    ),
                    "included": True,
                }
            )

        if selected and not breakdown and not issues:
            issues.append("No selected coins have balance to sell")

        summary = (
            f"Selling {len(breakdown)} coin(s) · est. "
            f"{total_value:.2f} {quote} total"
            if breakdown
            else "Select coins with balance to sell"
        )

        return {
            "group_id": group_id,
            "group_name": group["name"],
            "quote": quote,
            "breakdown": breakdown,
            "summary_text": summary,
            "est_total_quote": f"{total_value:.4f}".rstrip("0").rstrip("."),
            "quote_balance": _fmt_amount(quote_available, 4),
            "quote_balance_after": _fmt_amount(quote_available + total_value, 4),
            "issues": issues,
            "can_sell": len(breakdown) > 0 and len(issues) == 0,
        }

    def sell_group(
        self,
        group_id: str,
        coins: list[str] | None = None,
        amounts: dict[str, str] | None = None,
        coin: str | None = None,
        amount: str | None = None,
        sell_all: bool = False,
    ) -> dict[str, Any]:
        group = get_group(group_id)
        if not group:
            raise ValueError("Group not found")

        quote = group.get("quote") or DEFAULT_QUOTE

        # Legacy single-coin payload
        if coin and not coins:
            coins = [coin]
            if amount and not sell_all:
                amounts = {_normalize_coin(coin): amount}

        preview = self.preview_sell(group_id, coins, amounts)
        if preview["issues"]:
            raise ValueError(
                "Cannot sell — fix these issues first:\n"
                + "\n".join(f"• {i}" for i in preview["issues"])
            )
        if not preview["breakdown"]:
            raise ValueError("No available balance to sell")

        requests = [
            TradeRequest(
                coin=row["coin"],
                amount=row["amount"],
                side="sell",
                order_type="market",
                quote=quote,
            )
            for row in preview["breakdown"]
        ]
        results = self.trader.sell_multiple(requests)
        execution = summarize_order_results(results)
        if execution["failed_count"] > 0:
            raise ValueError(execution["message"])

        sold = [{"coin": r["coin"], "amount": r["amount"]} for r in preview["breakdown"]]

        return {
            "group_id": group_id,
            "group_name": group["name"],
            "action": "sell",
            "sold": sold,
            "quote": quote,
            "preview": preview,
            "execution": execution,
            "results": results,
        }
