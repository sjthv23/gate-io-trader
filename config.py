import os
from dotenv import load_dotenv

load_dotenv()

GATE_API_KEY = os.getenv("GATE_API_KEY", "")
GATE_API_SECRET = os.getenv("GATE_API_SECRET", "")
GATE_USE_TESTNET = os.getenv("GATE_USE_TESTNET", "false").lower() in ("1", "true", "yes")
DEFAULT_QUOTE = os.getenv("DEFAULT_QUOTE", "USDT").upper()
# Optional: fixed INR per 1 USDT if live rate APIs fail (e.g. INR_PER_USDT=85.5)
INR_PER_USDT = os.getenv("INR_PER_USDT", "").strip()

LIVE_HOST = "https://api.gateio.ws/api/v4"
TESTNET_HOST = "https://api-testnet.gateapi.io/api/v4"

TESTNET_PORTAL_URL = "https://testnet.gate.com/myaccount/funds/spot"
TESTNET_API_KEY_URL = "https://www.gate.com/myaccount/api_key"

# Gate.io batch limits: max 4 currency pairs, 10 orders per pair per request
MAX_PAIRS_PER_BATCH = 4
MAX_ORDERS_PER_PAIR = 10

# Custom order text prefix — Gate.io requires text to start with "t-"
BOT_ORDER_PREFIX = "t-gatebot-"
# Gate.io website trades typically use text "web"
WEBSITE_ORDER_TEXT = "web"


def get_api_host() -> str:
    return TESTNET_HOST if GATE_USE_TESTNET else LIVE_HOST
