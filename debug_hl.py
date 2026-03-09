"""Quick debug — check spot balances structure."""
import json, urllib.request
from dotenv import load_dotenv
load_dotenv()
import os

WALLET   = os.environ.get("HL_WALLET_ADDRESS", "").lower()
BASE_URL = "https://api.hyperliquid-testnet.xyz"

def hl_post(payload):
    data = json.dumps(payload).encode()
    req  = urllib.request.Request(BASE_URL + "/info", data=data,
                                  headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())

spot = hl_post({"type": "spotClearinghouseState", "user": WALLET})
print("Spot balances:")
print(json.dumps(spot.get("balances", []), indent=2))
