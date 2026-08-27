"""Gate.io dashboard — portfolio, markets, and coin groups."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from gate_api.exceptions import ApiException, GateApiException
from pydantic import BaseModel, Field

from config import (
    DEFAULT_QUOTE,
    GATE_API_KEY,
    GATE_API_SECRET,
    GATE_USE_TESTNET,
    TESTNET_API_KEY_URL,
    TESTNET_PORTAL_URL,
    get_api_host,
)
from gate_client import GateClient, GatePublicClient
from groups import (
    create_group,
    delete_group,
    get_group,
    GroupTrader,
    load_groups,
    update_group_allocations,
    update_group_coins,
)
from portfolio_history import build_analytics, build_coin_analysis, build_group_analysis, record_snapshot
from fx_rates import get_inr_rate_meta

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="Gate.io Dashboard")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

_client: GateClient | None = None
_public: GatePublicClient | None = None
_group_trader: GroupTrader | None = None


def _get_public() -> GatePublicClient:
    global _public
    if _public is None:
        _public = GatePublicClient()
    return _public


def _get_client() -> GateClient:
    global _client, _group_trader
    if _client is None:
        _client = GateClient()
        _group_trader = GroupTrader(_client)
    return _client


def _get_group_trader() -> GroupTrader:
    _get_client()
    return _group_trader  # type: ignore[return-value]


def _handle_api_error(exc: Exception) -> HTTPException:
    if isinstance(exc, GateApiException):
        return HTTPException(status_code=400, detail=f"Gate.io: {exc.label} — {exc.message}")
    if isinstance(exc, ApiException):
        return HTTPException(status_code=400, detail=f"API error: {exc}")
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


def _keys_status() -> tuple[bool, str | None]:
    if not GATE_API_KEY:
        return False, "missing_key"
    if not GATE_API_SECRET:
        return False, "missing_secret"
    placeholders = ("your_", "paste_", "example")
    if any(
        GATE_API_KEY.lower().startswith(p) or GATE_API_SECRET.lower().startswith(p)
        for p in placeholders
    ):
        return False, "placeholder_values"
    return True, None


class CreateGroupPayload(BaseModel):
    name: str
    coins: list[str] = Field(min_length=1)
    quote: str | None = None
    allocations: dict[str, str] | None = None


class UpdateAllocationsPayload(BaseModel):
    allocations: dict[str, str]


class UpdateGroupCoinsPayload(BaseModel):
    coins: list[str] = Field(min_length=1)


class GroupBuyPayload(BaseModel):
    total_amount: str


class GroupSellPayload(BaseModel):
    coins: list[str] | None = None
    amounts: dict[str, str] | None = None
    coin: str | None = None
    amount: str | None = None
    sell_all: bool = False


class SellPreviewPayload(BaseModel):
    coins: list[str] | None = None
    amounts: dict[str, str] | None = None


@app.get("/")
async def index():
    return FileResponse(
        BASE_DIR / "static" / "index.html",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@app.get("/api/status")
async def status():
    configured, issue = _keys_status()
    is_testnet = GATE_USE_TESTNET
    return {
        "configured": configured,
        "config_issue": issue,
        "mode": "testnet" if is_testnet else "live",
        "default_quote": DEFAULT_QUOTE,
        "api_host": get_api_host(),
        "testnet_portal": TESTNET_PORTAL_URL if is_testnet else None,
        "api_key_url": TESTNET_API_KEY_URL if is_testnet else "https://www.gate.com/myaccount/api_key",
    }


@app.get("/api/portfolio")
async def portfolio(quote: str | None = None):
    """Tab 1 — current assets, portfolio analysis, and value history."""
    try:
        data = _get_client().get_portfolio_analysis(quote)
        total = float(data.get("total_value") or 0)
        q = data.get("quote") or DEFAULT_QUOTE
        if total > 0:
            record_snapshot(total, q)
        data["analytics"] = build_analytics(
            total, q, data.get("assets") or [], public=_get_public()
        )
        fx = get_inr_rate_meta()
        data["inr_rate"] = fx.get("inr_rate")
        data["inr_source"] = fx.get("inr_source")
        return data
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except (GateApiException, ApiException) as e:
        raise _handle_api_error(e)


@app.get("/api/portfolio/asset/{coin}")
async def portfolio_asset_analysis(coin: str, quote: str | None = None):
    """Per-coin analysis for a holding in the spot wallet."""
    try:
        data = _get_client().get_portfolio_analysis(quote)
        sym = coin.strip().upper()
        assets = data.get("assets") or []
        asset = next((a for a in assets if (a.get("currency") or "").upper() == sym), None)
        if not asset:
            raise HTTPException(status_code=404, detail=f"{sym} is not in your spot wallet")
        total = float(data.get("total_value") or 0)
        q = data.get("quote") or DEFAULT_QUOTE
        analysis = build_coin_analysis(asset, q, _get_public(), portfolio_total=total)
        fx = get_inr_rate_meta()
        analysis["inr_rate"] = fx.get("inr_rate")
        analysis["inr_source"] = fx.get("inr_source")
        return analysis
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except (GateApiException, ApiException) as e:
        raise _handle_api_error(e)


@app.get("/api/markets")
async def markets(quote: str | None = None):
    """Tab 2 — all tradable coins with live prices from Gate.io."""
    try:
        coins = _get_public().list_markets(quote)
        return {"quote": quote or DEFAULT_QUOTE, "markets": coins, "count": len(coins)}
    except (GateApiException, ApiException) as e:
        raise _handle_api_error(e)


@app.get("/api/groups")
async def groups():
    """Tab 3 — all groups with live holdings."""
    try:
        return {"groups": _get_group_trader().list_groups_with_holdings()}
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except (GateApiException, ApiException) as e:
        raise _handle_api_error(e)


@app.post("/api/groups")
async def create_group_endpoint(payload: CreateGroupPayload):
    try:
        group = create_group(
            payload.name,
            payload.coins,
            payload.quote,
            payload.allocations,
        )
        holdings = _get_client().get_group_holdings(group["coins"], group.get("quote"))
        return {"group": {**group, "holdings": holdings}}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.put("/api/groups/{group_id}/allocations")
@app.post("/api/groups/{group_id}/allocations")
async def update_allocations(group_id: str, payload: UpdateAllocationsPayload):
    try:
        group = update_group_allocations(group_id, payload.allocations)
        holdings = _get_client().get_group_holdings(group["coins"], group.get("quote"))
        return {"group": {**group, "holdings": holdings}}
    except ValueError as e:
        msg = str(e)
        if msg == "Group not found":
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=400, detail=msg)


@app.put("/api/groups/{group_id}/coins")
@app.post("/api/groups/{group_id}/coins")
async def update_group_coins_endpoint(group_id: str, payload: UpdateGroupCoinsPayload):
    try:
        group = update_group_coins(group_id, payload.coins)
        holdings = _get_client().get_group_holdings(group["coins"], group.get("quote"))
        return {"group": {**group, "holdings": holdings}}
    except ValueError as e:
        msg = str(e)
        if msg == "Group not found":
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=400, detail=msg)


@app.get("/api/groups/{group_id}/analysis")
async def group_analysis(group_id: str):
    """Full analysis for a group's combined holdings."""
    group = get_group(group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    try:
        holdings = _get_client().get_group_holdings(group["coins"], group.get("quote"))
        analysis = build_group_analysis(group, holdings, _get_public())
        fx = get_inr_rate_meta()
        analysis["inr_rate"] = fx.get("inr_rate")
        analysis["inr_source"] = fx.get("inr_source")
        return analysis
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except (GateApiException, ApiException) as e:
        raise _handle_api_error(e)


@app.get("/api/groups/{group_id}/buy-preview")
async def buy_preview(group_id: str, total_amount: str):
    try:
        return _get_group_trader().preview_buy(group_id, total_amount)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/groups/{group_id}/warm-cache")
async def warm_group_cache(group_id: str):
    """Preload pair metadata so buy preview is instant."""
    group = get_group(group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    _get_client().warm_pair_cache(group["coins"], group.get("quote"))
    return {"ok": True}


@app.delete("/api/groups/{group_id}")
async def delete_group_endpoint(group_id: str):
    if not delete_group(group_id):
        raise HTTPException(status_code=404, detail="Group not found")
    return {"deleted": group_id}


@app.post("/api/groups/{group_id}/buy")
async def buy_group(group_id: str, payload: GroupBuyPayload):
    """Buy group coins — split by allocation % or equally."""
    try:
        return _get_group_trader().buy_group(group_id, payload.total_amount)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except (GateApiException, ApiException) as e:
        raise _handle_api_error(e)


@app.post("/api/groups/{group_id}/sell-preview")
async def sell_preview(group_id: str, payload: SellPreviewPayload):
    try:
        return _get_group_trader().preview_sell(
            group_id, payload.coins, payload.amounts
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/groups/{group_id}/sell")
async def sell_group(group_id: str, payload: GroupSellPayload):
    """Sell selected coins or full balances in a group."""
    try:
        return _get_group_trader().sell_group(
            group_id,
            payload.coins,
            payload.amounts,
            payload.coin,
            payload.amount,
            payload.sell_all,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except (GateApiException, ApiException) as e:
        raise _handle_api_error(e)


@app.get("/api/fx/inr")
async def fx_inr():
    """USDT/INR rate for INR display toggle."""
    return get_inr_rate_meta()


@app.get("/api/transactions")
async def list_transactions(
    source: Literal["all", "bot", "website", "manual"] = "all",
    limit: int = 50,
    page: int = 1,
):
    """Spot trade history with bot vs Gate website filter."""
    try:
        return _get_client().list_transactions(limit=limit, page=page, source=source)
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except (GateApiException, ApiException) as e:
        raise _handle_api_error(e)
