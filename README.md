# Gate.io Dashboard

Three-tab dashboard for Gate.io spot trading — all data live from the Gate.io API.

## Tabs

| Tab | What it does |
|-----|----------------|
| **Portfolio** | Current spot assets, value in USDT, 24h change, allocation breakdown |
| **All Coins** | Every tradable coin from Gate.io with live price, 24h change, volume — select coins and create groups |
| **Groups** | Saved coin groups — buy (total split equally), sell one or all, delete group |

## Setup

### 1. API keys

1. Log in to [Gate.io](https://www.gate.io/)
2. Create **API v4** keys with **Spot Trading** enabled
3. For demo: set `GATE_USE_TESTNET=true` and use testnet keys

### 2. Install & configure

```bash
cd gate-io-trader
pip install -r requirements.txt
copy .env.example .env
```

Edit `.env`:

```env
GATE_API_KEY=your_key
GATE_API_SECRET=your_secret
DEFAULT_QUOTE=USDT
```

### 3. Run

```bash
python -m uvicorn web_app:app --reload --host 127.0.0.1 --port 8765
```

Open **http://127.0.0.1:8765**

## How groups work

1. **All Coins** — check coins you want, click **Create group**, name it
2. **Groups** — click **Buy equal split**, enter total USDT (e.g. 150 for 3 coins = 50 each)
3. **Sell** — sell all holdings in the group, or pick one coin and amount

Groups are saved in `groups.json`. Deleting a group does not sell coins.

## Project structure

```
gate-io-trader/
  web_app.py       # FastAPI server
  gate_client.py   # Gate.io API (portfolio, markets, orders)
  groups.py        # Group CRUD + equal-split buy/sell
  trader.py        # Order execution
  groups.json      # Saved groups
  static/          # Dashboard UI
  config.py
  .env
```

## Safety

- Never commit `.env` or share API keys
- Start on testnet or small amounts on live
