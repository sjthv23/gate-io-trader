"""Trading logic: batch buy/sell and individual sells."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal

import gate_api
from gate_api.exceptions import ApiException, GateApiException

from config import BOT_ORDER_PREFIX, DEFAULT_QUOTE
from gate_client import GateClient


def bot_order_text() -> str:
    return f"{BOT_ORDER_PREFIX}{uuid.uuid4().hex[:12]}"

OrderSide = Literal["buy", "sell"]
OrderType = Literal["market", "limit"]


@dataclass
class TradeRequest:
    coin: str
    amount: str
    side: OrderSide
    order_type: OrderType = "market"
    price: str | None = None
    quote: str | None = None


class OrderExecutionError(ValueError):
    """Raised when one or more orders fail to execute."""

    def __init__(self, message: str, results: list[dict]) -> None:
        super().__init__(message)
        self.results = results


def _build_gate_order(client: GateClient, req: TradeRequest) -> gate_api.Order:
    pair = client.pair(req.coin, req.quote)
    order = gate_api.Order(
        currency_pair=pair,
        side=req.side,
        amount=str(req.amount),
        type=req.order_type,
        account="spot",
        text=bot_order_text(),
    )
    if req.order_type == "limit" and req.price:
        order.price = str(req.price)
        order.time_in_force = "gtc"
    else:
        order.time_in_force = "ioc"
    return order


def summarize_order_results(results: list[dict]) -> dict:
    ok = [r for r in results if r.get("ok")]
    bad = [r for r in results if not r.get("ok")]
    filled = sum(float(r.get("filled_total") or 0) for r in ok)
    quote = DEFAULT_QUOTE
    if ok:
        quote = ok[0].get("currency_pair", "").split("_")[1] or DEFAULT_QUOTE

    parts: list[str] = []
    for r in ok:
        coin = r.get("coin") or r.get("currency_pair", "").split("_")[0]
        spent = r.get("filled_total") or r.get("amount")
        parts.append(f"{coin} {spent} {quote}")

    fail_parts = [
        f"{r.get('coin') or r.get('currency_pair')}: {r.get('error') or 'failed'}"
        for r in bad
    ]

    if ok and not bad:
        message = f"Filled {len(ok)} order(s): " + ", ".join(parts)
    elif ok and bad:
        message = (
            f"Partial fill — {len(ok)} succeeded, {len(bad)} failed. "
            f"OK: {', '.join(parts)}. Failed: {', '.join(fail_parts)}"
        )
    else:
        message = "All orders failed: " + "; ".join(fail_parts)

    return {
        "success_count": len(ok),
        "failed_count": len(bad),
        "filled_total_quote": f"{filled:.4f}".rstrip("0").rstrip("."),
        "message": message,
        "ok": len(bad) == 0,
    }


class Trader:
    def __init__(self, client: GateClient | None = None) -> None:
        self.client = client or GateClient()

    def buy_multiple(self, requests: list[TradeRequest]) -> list[dict]:
        """Buy multiple coins. Market buy amount = quote currency (e.g. USDT to spend)."""
        for r in requests:
            r.side = "buy"
        return self._execute_orders(requests)

    def sell_multiple(self, requests: list[TradeRequest]) -> list[dict]:
        for r in requests:
            r.side = "sell"
        return self._execute_orders(requests)

    def sell_single(
        self,
        coin: str,
        amount: str,
        order_type: OrderType = "market",
        price: str | None = None,
        quote: str | None = None,
    ) -> dict:
        req = TradeRequest(
            coin=coin,
            amount=amount,
            side="sell",
            order_type=order_type,
            price=price,
            quote=quote,
        )
        results = self._execute_orders([req])
        return results[0]

    def buy_single(
        self,
        coin: str,
        amount: str,
        order_type: OrderType = "market",
        price: str | None = None,
        quote: str | None = None,
    ) -> dict:
        req = TradeRequest(
            coin=coin,
            amount=amount,
            side="buy",
            order_type=order_type,
            price=price,
            quote=quote,
        )
        results = self._execute_orders([req])
        return results[0]

    def _execute_orders(self, requests: list[TradeRequest]) -> list[dict]:
        """Place orders one-by-one so failures are visible and partial fills are possible."""
        if not requests:
            return []

        results: list[dict] = []
        failures: list[str] = []

        for req in requests:
            order = _build_gate_order(self.client, req)
            try:
                result = self.client.create_order(
                    currency_pair=order.currency_pair,
                    side=order.side,
                    amount=order.amount,
                    order_type=order.type,
                    price=order.price,
                    time_in_force=order.time_in_force,
                )
                formatted = self.client.format_order_result(result, coin=req.coin)
            except GateApiException as e:
                formatted = self.client.format_failed_order(
                    req.coin,
                    req.amount,
                    e.label,
                    e.message,
                    req.quote,
                )
            except ApiException as e:
                formatted = self.client.format_failed_order(
                    req.coin,
                    req.amount,
                    "API_ERROR",
                    str(e),
                    req.quote,
                )

            results.append(formatted)
            if not formatted.get("ok"):
                failures.append(
                    f"{req.coin}: {formatted.get('error') or 'order failed'}"
                )

        if failures and len(failures) == len(requests):
            raise OrderExecutionError(
                "All orders failed: " + "; ".join(failures),
                results,
            )

        return results
