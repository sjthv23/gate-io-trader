"""Gate.io API client — portfolio, markets, and spot trading."""

from __future__ import annotations

import time
import uuid
from typing import Any

import gate_api

from config import (
    BOT_ORDER_PREFIX,
    DEFAULT_QUOTE,
    GATE_API_KEY,
    GATE_API_SECRET,
    LIVE_HOST,
    get_api_host,
    WEBSITE_ORDER_TEXT,
)

MARKETS_CACHE_TTL = 45
_markets_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_pair_info_cache: dict[str, dict[str, Any]] = {}
_pairs_cache_loaded: set[str] = set()


def _ticker_fields(t: Any) -> dict[str, Any]:
    change = getattr(t, "change_percentage", None) or getattr(t, "change", None)
    return {
        "last": t.last or "0",
        "lowest_ask": t.lowest_ask,
        "highest_bid": t.highest_bid,
        "high_24h": getattr(t, "high_24h", None),
        "low_24h": getattr(t, "low_24h", None),
        "change_pct": change,
        "base_volume": getattr(t, "base_volume", None),
        "quote_volume": getattr(t, "quote_volume", None),
    }


def _parse_candlestick(c: Any) -> dict[str, Any] | None:
    """Parse Gate spot candle: [t, quote_vol, close, high, low, open, ...]."""
    try:
        if isinstance(c, list):
            ts = int(c[0])
            close = float(c[2])
            high = float(c[3])
            low = float(c[4])
            open_ = float(c[5])
            quote_vol = float(c[1]) if len(c) > 1 and c[1] else None
        else:
            ts = int(getattr(c, "t", 0) or getattr(c, "timestamp", 0))
            close = float(getattr(c, "c", None) or getattr(c, "close", 0))
            high = float(getattr(c, "h", None) or getattr(c, "high", close))
            low = float(getattr(c, "l", None) or getattr(c, "low", close))
            open_ = float(getattr(c, "o", None) or getattr(c, "open", close))
            quote_vol = getattr(c, "v", None) or getattr(c, "quote_volume", None)
            if quote_vol is not None:
                quote_vol = float(quote_vol)
        if close <= 0:
            return None
        return {
            "ts": ts,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "quote_volume": quote_vol,
        }
    except (TypeError, ValueError, IndexError):
        return None


class GatePublicClient:
    """Public market data — no API keys required."""

    def __init__(self) -> None:
        configuration = gate_api.Configuration(host=get_api_host())
        self._spot = gate_api.SpotApi(gate_api.ApiClient(configuration))

    def pair(self, coin: str, quote: str | None = None) -> str:
        base = coin.strip().upper()
        q = (quote or DEFAULT_QUOTE).strip().upper()
        if "_" in base:
            return base
        return f"{base}_{q}"

    def list_markets(self, quote: str | None = None, use_cache: bool = True) -> list[dict[str, Any]]:
        """All tradable spot pairs for a quote with live ticker data."""
        q = (quote or DEFAULT_QUOTE).strip().upper()
        now = time.time()
        if use_cache and q in _markets_cache:
            ts, cached = _markets_cache[q]
            if now - ts < MARKETS_CACHE_TTL:
                return cached

        pairs = self._spot.list_currency_pairs()
        tradable = [p for p in pairs if p.quote == q and p.trade_status == "tradable"]

        tickers = self._spot.list_tickers()
        ticker_map = {t.currency_pair: t for t in tickers}

        markets: list[dict[str, Any]] = []
        for p in tradable:
            t = ticker_map.get(p.id)
            if not t:
                continue
            fields = _ticker_fields(t)
            markets.append(
                {
                    "coin": p.base,
                    "pair": p.id,
                    "quote": p.quote,
                    **fields,
                }
            )

        markets.sort(key=lambda m: float(m.get("quote_volume") or 0), reverse=True)
        _markets_cache[q] = (now, markets)
        return markets

    def get_ticker(self, currency_pair: str) -> dict[str, Any]:
        tickers = self._spot.list_tickers(currency_pair=currency_pair)
        if not tickers:
            raise ValueError(f"No ticker for {currency_pair}")
        t = tickers[0]
        return {
            "currency_pair": t.currency_pair,
            **{k: v for k, v in _ticker_fields(t).items() if k != "base_volume"},
        }

    def get_price_history(
        self,
        currency_pair: str,
        interval: str = "1h",
        limit: int = 24,
    ) -> list[dict[str, Any]]:
        """Recent close prices for charting (default last 24 hourly candles)."""
        candles = self.get_candle_history(currency_pair, interval=interval, limit=limit)
        return [{"ts": c["ts"], "price": c["close"]} for c in candles]

    def get_candle_history(
        self,
        currency_pair: str,
        interval: str = "1h",
        limit: int = 24,
    ) -> list[dict[str, Any]]:
        """OHLC candlesticks for charting."""
        try:
            raw = self._spot.list_candlesticks(
                currency_pair, interval=interval, limit=limit
            )
        except Exception:
            return []
        points: list[dict[str, Any]] = []
        for c in raw or []:
            parsed = _parse_candlestick(c)
            if parsed:
                points.append(parsed)
        return points

    def get_tickers_for_coins(self, coins: list[str], quote: str | None = None) -> dict[str, dict[str, Any]]:
        """Fetch tickers only for specific base coins (fast — no full market scan)."""
        q = (quote or DEFAULT_QUOTE).strip().upper()
        result: dict[str, dict[str, Any]] = {}
        for coin in coins:
            sym = coin.strip().upper().split("_")[0]
            if not sym or sym == q:
                continue
            pair = self.pair(sym, q)
            try:
                tickers = self._spot.list_tickers(currency_pair=pair)
                if tickers:
                    result[sym] = _ticker_fields(tickers[0])
            except Exception:
                continue
        return result

    def get_usdt_inr_rate(self) -> float | None:
        """Deprecated — use fx_rates.get_usdt_inr_rate()."""
        from fx_rates import get_usdt_inr_rate as _get

        return _get()


class GateClient:
    def __init__(self) -> None:
        if not GATE_API_KEY or not GATE_API_SECRET:
            raise ValueError(
                "Missing GATE_API_KEY or GATE_API_SECRET. Copy .env.example to .env and fill in your keys."
            )

        host = get_api_host()
        self.host = host
        configuration = gate_api.Configuration(
            host=host,
            key=GATE_API_KEY,
            secret=GATE_API_SECRET,
        )
        self._api_client = gate_api.ApiClient(configuration)
        self._spot = gate_api.SpotApi(self._api_client)
        self._public = GatePublicClient()

    def pair(self, coin: str, quote: str | None = None) -> str:
        return self._public.pair(coin, quote)

    def _ensure_pair_cache(self, quote: str | None = None) -> None:
        """Load all pair metadata once per quote (fast lookups, no per-coin API calls)."""
        q = (quote or DEFAULT_QUOTE).strip().upper()
        if q in _pairs_cache_loaded:
            return
        pairs = self._spot.list_currency_pairs()
        for row in pairs:
            if row.quote != q:
                continue
            _pair_info_cache[row.id] = {
                "coin": row.base,
                "pair": row.id,
                "quote": q,
                "trade_status": row.trade_status,
                "min_quote_amount": float(row.min_quote_amount or 3),
                "min_base_amount": float(row.min_base_amount or 0),
            }
        _pairs_cache_loaded.add(q)

    def warm_pair_cache(self, coins: list[str], quote: str | None = None) -> None:
        """Preload pair metadata and tradeability for a group's coins."""
        q = (quote or DEFAULT_QUOTE).strip().upper()
        self._ensure_pair_cache(q)
        for coin in coins:
            try:
                info = self.get_pair_info(coin, q)
            except ValueError:
                continue
            pair = info["pair"]
            if "ticker_ok" in _pair_info_cache.get(pair, {}):
                continue
            try:
                tickers = self._public._spot.list_tickers(currency_pair=pair)
                ticker_ok = bool(tickers)
            except Exception:
                ticker_ok = False
            _pair_info_cache[pair] = {**_pair_info_cache[pair], "ticker_ok": ticker_ok}

    def get_pair_info(self, coin: str, quote: str | None = None) -> dict[str, Any]:
        """Tradability and minimum order size for a spot pair."""
        q = (quote or DEFAULT_QUOTE).strip().upper()
        sym = coin.strip().upper().split("_")[0]
        pair = self.pair(sym, q)
        if pair in _pair_info_cache:
            return _pair_info_cache[pair]

        self._ensure_pair_cache(q)
        if pair in _pair_info_cache:
            return _pair_info_cache[pair]

        raise ValueError(f"{sym} is not listed on Gate.io ({pair})")

    def validate_buy_amounts(
        self,
        amounts: dict[str, str],
        quote: str | None = None,
        *,
        check_ticker: bool = False,
    ) -> list[str]:
        """Return human-readable issues for order sizes / tradability."""
        q = (quote or DEFAULT_QUOTE).strip().upper()
        self._ensure_pair_cache(q)
        issues: list[str] = []
        for coin, raw in amounts.items():
            amt = float(raw)
            if amt <= 0:
                continue
            try:
                info = self.get_pair_info(coin, q)
            except ValueError as e:
                issues.append(str(e))
                continue
            if info["trade_status"] != "tradable":
                issues.append(f"{coin}: market is not tradable ({info['trade_status']})")
            min_q = info["min_quote_amount"]
            if amt < min_q:
                issues.append(
                    f"{coin}: {amt:g} {q} is below Gate.io minimum ({min_q:g} {q})"
                )
            if not check_ticker:
                continue
            pair = info["pair"]
            ticker_ok = info.get("ticker_ok")
            if ticker_ok is False:
                issues.append(
                    f"{coin}: not available for trading on Gate.io testnet ({pair})"
                )
            elif ticker_ok is None:
                try:
                    tickers = self._public._spot.list_tickers(currency_pair=pair)
                    ok = bool(tickers)
                    _pair_info_cache[pair] = {**info, "ticker_ok": ok}
                    if not ok:
                        issues.append(
                            f"{coin}: not available for trading on Gate.io testnet ({pair})"
                        )
                except Exception:
                    issues.append(
                        f"{coin}: not available for trading on this account ({pair})"
                    )
        return issues

    def _fetch_spot_accounts(self) -> list[Any]:
        if hasattr(self._spot, "list_spot_accounts"):
            return self._spot.list_spot_accounts()
        return self._api_client.call_api(
            "/spot/accounts",
            "GET",
            path_params={},
            query_params={},
            header_params={},
            body=None,
            post_params={},
            files={},
            response_type="list[dict]",
            auth_settings=["apiv4"],
            _return_http_data_only=True,
        )

    def _account_row(self, a: Any) -> dict[str, str]:
        return {
            "currency": a["currency"] if isinstance(a, dict) else a.currency,
            "available": a["available"] if isinstance(a, dict) else a.available,
            "locked": a["locked"] if isinstance(a, dict) else a.locked,
        }

    def list_balances(self, include_zero: bool = False) -> list[dict[str, str]]:
        accounts = self._fetch_spot_accounts()
        rows = [self._account_row(a) for a in accounts]
        if not include_zero:
            rows = [
                r
                for r in rows
                if float(r["available"]) > 0 or float(r["locked"]) > 0
            ]
        return rows

    def list_markets(self, quote: str | None = None) -> list[dict[str, Any]]:
        return self._public.list_markets(quote)

    def get_portfolio_analysis(self, quote: str | None = None) -> dict[str, Any]:
        """Current spot holdings with value, allocation, and summary stats."""
        q = (quote or DEFAULT_QUOTE).strip().upper()
        accounts = self._fetch_spot_accounts()

        held_currencies: list[str] = []
        for a in accounts:
            row = self._account_row(a)
            total = float(row["available"]) + float(row["locked"])
            if total > 0:
                held_currencies.append(row["currency"])

        tickers = self._public.get_tickers_for_coins(held_currencies, q)

        assets: list[dict[str, Any]] = []
        total_value = 0.0

        for a in accounts:
            row = self._account_row(a)
            available = float(row["available"])
            locked = float(row["locked"])
            total = available + locked
            if total <= 0:
                continue

            currency = row["currency"]
            price: float | None = None
            value: float | None = None
            change_pct: str | None = None

            if currency == q:
                price = 1.0
                value = total
                high_price = 1.0
                low_price = 1.0
            else:
                market = tickers.get(currency)
                if market:
                    price = float(market["last"])
                    value = total * price
                    change_pct = market.get("change_pct")
                    try:
                        high_price = float(market.get("high_24h") or price)
                        low_price = float(market.get("low_24h") or price)
                    except (TypeError, ValueError):
                        high_price = price
                        low_price = price
                else:
                    high_price = None
                    low_price = None

            value_high = None
            value_low = None
            if value is not None and high_price is not None and low_price is not None:
                value_high = total * high_price
                value_low = total * low_price

            if value is not None:
                total_value += value

            assets.append(
                {
                    "currency": currency,
                    "available": row["available"],
                    "locked": row["locked"],
                    "total": f"{total:.8f}".rstrip("0").rstrip("."),
                    "price": f"{price:.8f}".rstrip("0").rstrip(".") if price is not None else None,
                    "value_quote": f"{value:.4f}".rstrip("0").rstrip(".") if value is not None else None,
                    "change_pct": change_pct,
                    "pair": self.pair(currency, q) if currency != q else None,
                    "high_24h": (
                        f"{high_price:.8f}".rstrip("0").rstrip(".")
                        if high_price is not None
                        else None
                    ),
                    "low_24h": (
                        f"{low_price:.8f}".rstrip("0").rstrip(".")
                        if low_price is not None
                        else None
                    ),
                    "value_high_24h": (
                        f"{value_high:.4f}".rstrip("0").rstrip(".")
                        if value_high is not None
                        else None
                    ),
                    "value_low_24h": (
                        f"{value_low:.4f}".rstrip("0").rstrip(".")
                        if value_low is not None
                        else None
                    ),
                }
            )

        assets.sort(key=lambda x: float(x["value_quote"] or 0), reverse=True)

        for a in assets:
            val = float(a["value_quote"] or 0)
            a["allocation_pct"] = (
                f"{(val / total_value * 100):.2f}" if total_value > 0 and val > 0 else "0"
            )

        top = assets[0] if assets else None
        holdings_count = len(assets)

        return {
            "quote": q,
            "total_value": f"{total_value:.4f}".rstrip("0").rstrip("."),
            "holdings_count": holdings_count,
            "top_holding": top["currency"] if top else None,
            "top_holding_pct": top["allocation_pct"] if top else None,
            "assets": assets,
        }

    def get_group_holdings(self, coins: list[str], quote: str | None = None) -> list[dict[str, Any]]:
        """Balances for coins in a group with live prices."""
        q = (quote or DEFAULT_QUOTE).strip().upper()
        balances = {b["currency"]: b for b in self.list_balances(include_zero=False)}
        market_map = self._public.get_tickers_for_coins(coins, q)

        holdings: list[dict[str, Any]] = []
        for coin in coins:
            sym = coin.strip().upper()
            row = balances.get(sym)
            market = market_map.get(sym)
            available = float(row["available"]) if row else 0.0
            locked = float(row["locked"]) if row else 0.0
            total = available + locked
            price = float(market["last"]) if market else None
            value = total * price if price is not None else None

            holdings.append(
                {
                    "coin": sym,
                    "pair": self.pair(sym, q),
                    "available": row["available"] if row else "0",
                    "locked": row["locked"] if row else "0",
                    "total": f"{total:.8f}".rstrip("0").rstrip(".") if total > 0 else "0",
                    "last": market.get("last") if market else None,
                    "change_pct": market.get("change_pct") if market else None,
                    "value_quote": (
                        f"{value:.4f}".rstrip("0").rstrip(".") if value is not None else None
                    ),
                }
            )
        return holdings

    def create_order(
        self,
        currency_pair: str,
        side: str,
        amount: str,
        order_type: str = "market",
        price: str | None = None,
        time_in_force: str = "ioc",
    ) -> gate_api.Order:
        order = gate_api.Order(
            currency_pair=currency_pair,
            side=side,
            amount=str(amount),
            type=order_type,
            account="spot",
            text=f"{BOT_ORDER_PREFIX}{uuid.uuid4().hex[:12]}",
        )
        if order_type == "limit" and price:
            order.price = str(price)
            order.time_in_force = "gtc"
        else:
            order.time_in_force = time_in_force

        return self._spot.create_order(order)

    def create_batch_orders(self, orders: list[gate_api.Order]) -> list[gate_api.BatchOrder]:
        return self._spot.create_batch_orders(orders)

    def format_order_result(self, order: Any, coin: str | None = None) -> dict[str, Any]:
        order_id = getattr(order, "id", None) or getattr(order, "order_id", None)
        succeeded = getattr(order, "succeeded", None)
        label = getattr(order, "label", None)
        message = getattr(order, "message", None)
        status = getattr(order, "status", None)
        finish_as = getattr(order, "finish_as", None)
        filled_total = getattr(order, "filled_total", None) or getattr(order, "fill_price", None)

        if succeeded is False:
            ok = False
        elif label:
            ok = False
        elif finish_as == "filled" or status == "closed":
            ok = True
        elif order_id:
            ok = finish_as not in ("cancelled", "expired") and status != "cancelled"
        else:
            ok = False

        pair = getattr(order, "currency_pair", None)
        base_coin = coin or (pair.split("_")[0] if pair else None)

        return {
            "id": order_id,
            "coin": base_coin,
            "currency_pair": pair,
            "side": getattr(order, "side", None),
            "amount": getattr(order, "amount", None),
            "price": getattr(order, "price", None),
            "type": getattr(order, "type", None),
            "status": status,
            "filled_total": filled_total,
            "fill_price": getattr(order, "fill_price", None),
            "finish_as": finish_as,
            "succeeded": succeeded,
            "label": label,
            "message": message,
            "ok": ok,
            "error": message if not ok else None,
        }

    def format_failed_order(
        self,
        coin: str,
        amount: str,
        label: str | None,
        message: str | None,
        quote: str | None = None,
    ) -> dict[str, Any]:
        pair = self.pair(coin, quote)
        text = message or label or "Order failed"
        return {
            "id": None,
            "coin": coin,
            "currency_pair": pair,
            "side": "buy",
            "amount": amount,
            "price": None,
            "type": "market",
            "status": None,
            "filled_total": None,
            "fill_price": None,
            "finish_as": None,
            "succeeded": False,
            "label": label,
            "message": message,
            "ok": False,
            "error": text,
        }

    @staticmethod
    def classify_order_source(text: str | None) -> str:
        """bot | website | other"""
        if not text:
            return "other"
        if text == WEBSITE_ORDER_TEXT:
            return "website"
        if text.startswith(BOT_ORDER_PREFIX) or (
            text.startswith("t-") and text != WEBSITE_ORDER_TEXT
        ):
            return "bot"
        return "other"

    def format_trade(self, trade: Any) -> dict[str, Any]:
        pair = getattr(trade, "currency_pair", "") or ""
        base = pair.split("_")[0] if pair else ""
        quote = pair.split("_")[1] if "_" in pair else DEFAULT_QUOTE
        text = getattr(trade, "text", None) or ""
        source = self.classify_order_source(text)
        amount = getattr(trade, "amount", None)
        price = getattr(trade, "price", None)
        value = None
        if amount and price:
            try:
                value = float(amount) * float(price)
            except (TypeError, ValueError):
                value = None
        create_ms = getattr(trade, "create_time_ms", None)
        create_time = getattr(trade, "create_time", None)
        return {
            "id": getattr(trade, "id", None),
            "order_id": getattr(trade, "order_id", None),
            "currency_pair": pair,
            "coin": base,
            "quote": quote,
            "side": getattr(trade, "side", None),
            "amount": amount,
            "price": price,
            "value_quote": (
                f"{value:.4f}".rstrip("0").rstrip(".") if value is not None else None
            ),
            "fee": getattr(trade, "fee", None),
            "fee_currency": getattr(trade, "fee_currency", None),
            "role": getattr(trade, "role", None),
            "text": text,
            "source": source,
            "is_bot": source == "bot",
            "create_time": create_time,
            "create_time_ms": create_ms,
        }

    def list_transactions(
        self,
        limit: int = 50,
        page: int = 1,
        source: str = "all",
    ) -> dict[str, Any]:
        """Recent spot trades with bot vs website classification."""
        limit = max(1, min(limit, 100))
        page = max(1, page)
        fetch_limit = limit if source == "all" else min(100, limit * 4)
        trades = self._spot.list_my_trades(limit=fetch_limit, page=page)
        rows = [self.format_trade(t) for t in trades]

        if source == "bot":
            rows = [r for r in rows if r["source"] == "bot"]
        elif source == "website":
            rows = [r for r in rows if r["source"] == "website"]
        elif source == "manual":
            rows = [r for r in rows if r["source"] != "bot"]

        rows = rows[:limit]

        return {
            "transactions": rows,
            "count": len(rows),
            "page": page,
            "limit": limit,
            "filter": source,
        }
