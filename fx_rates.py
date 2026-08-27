"""USDT/INR rate for display — Gate pair, public FX APIs, or .env override."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any

import gate_api

from config import GATE_USE_TESTNET, LIVE_HOST, TESTNET_HOST

FX_CACHE_TTL = 3600
_inr_cache: dict[str, Any] = {"rate": None, "ts": 0.0, "source": None}


def _fetch_json(url: str, timeout: float = 10.0) -> dict | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "gate-io-trader/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.URLError, json.JSONDecodeError, OSError, ValueError):
        return None


def _from_gate() -> float | None:
    for host in (TESTNET_HOST if GATE_USE_TESTNET else LIVE_HOST, LIVE_HOST):
        try:
            spot = gate_api.SpotApi(gate_api.ApiClient(gate_api.Configuration(host=host)))
            tickers = spot.list_tickers(currency_pair="USDT_INR")
            if tickers and tickers[0].last:
                return float(tickers[0].last)
        except Exception:
            continue
    return None


def _from_er_api() -> float | None:
    data = _fetch_json("https://open.er-api.com/v6/latest/USD")
    if not data or data.get("result") != "success":
        return None
    inr = data.get("rates", {}).get("INR")
    if inr is None:
        return None
    return float(inr)


def _from_coingecko() -> float | None:
    data = _fetch_json(
        "https://api.coingecko.com/api/v3/simple/price?ids=tether&vs_currencies=inr"
    )
    if not data:
        return None
    inr = data.get("tether", {}).get("inr")
    if inr is None:
        return None
    return float(inr)


def get_usdt_inr_rate(force_refresh: bool = False) -> float | None:
    """
    Return how many INR per 1 USDT.
    Order: .env INR_PER_USDT → cache → Gate → open.er-api.com → CoinGecko.
    """
    manual = os.getenv("INR_PER_USDT", "").strip()
    if manual:
        try:
            rate = float(manual)
            if rate > 0:
                _inr_cache.update({"rate": rate, "ts": time.time(), "source": "env"})
                return rate
        except ValueError:
            pass

    now = time.time()
    if (
        not force_refresh
        and _inr_cache.get("rate")
        and now - float(_inr_cache.get("ts") or 0) < FX_CACHE_TTL
    ):
        return float(_inr_cache["rate"])

    rate = _from_gate()
    source = "gate" if rate else None
    if rate is None:
        rate = _from_er_api()
        source = "er-api" if rate else None
    if rate is None:
        rate = _from_coingecko()
        source = "coingecko" if rate else None

    if rate and rate > 0:
        _inr_cache.update({"rate": rate, "ts": now, "source": source})
        return rate
    return _inr_cache.get("rate")  # stale cache if all fetches fail


def get_inr_rate_meta() -> dict[str, Any]:
    rate = get_usdt_inr_rate()
    return {
        "inr_rate": f"{rate:.4f}".rstrip("0").rstrip(".") if rate else None,
        "inr_source": _inr_cache.get("source"),
    }
