import os
import time
import hmac
import hashlib
import requests
from urllib.parse import urlencode


# =========================================================
# BINANCE TH
# READ-ONLY ACCOUNT INTEGRATION
# =========================================================

BINANCE_API_URL = "https://api.binance.th"

RECV_WINDOW = 5000


# =========================================================
# CREDENTIALS
# =========================================================

def get_credentials():

    api_key = os.getenv(
        "BINANCE_API_KEY"
    )

    api_secret = os.getenv(
        "BINANCE_API_SECRET"
    )

    if not api_key:
        raise RuntimeError(
            "BINANCE_API_KEY is missing"
        )

    if not api_secret:
        raise RuntimeError(
            "BINANCE_API_SECRET is missing"
        )

    return (
        api_key.strip(),
        api_secret.strip()
    )


# =========================================================
# SERVER TIME
# =========================================================

def get_server_time():

    response = requests.get(
        f"{BINANCE_API_URL}/api/v1/time",
        timeout=10
    )

    response.raise_for_status()

    data = response.json()

    if "serverTime" not in data:

        raise RuntimeError(
            f"Invalid Binance TH time response: {data}"
        )

    return int(
        data["serverTime"]
    )


# =========================================================
# SIGNED GET
# =========================================================

def signed_get(
    path,
    params=None
):

    api_key, api_secret = get_credentials()

    params = dict(
        params or {}
    )

    # Binance TH server timestamp.
    params["timestamp"] = get_server_time()

    params["recvWindow"] = RECV_WINDOW

    # IMPORTANT:
    # Sign exactly the parameter string that
    # will be sent to Binance TH.
    query_string = urlencode(
        params,
        doseq=True
    )

    signature = hmac.new(
        api_secret.encode("utf-8"),
        query_string.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

    params["signature"] = signature

    headers = {
        "Accept": "application/json",
        "X-MBX-APIKEY": api_key
    }

    response = requests.get(
        f"{BINANCE_API_URL}{path}",
        params=params,
        headers=headers,
        timeout=15
    )

    # -----------------------------------------------------
    # Return Binance TH's real error.
    # -----------------------------------------------------

    if response.status_code != 200:

        try:

            error_body = response.json()

        except Exception:

            error_body = {
                "raw": response.text
            }

        raise RuntimeError(
            "Binance TH API error "
            f"HTTP {response.status_code}: "
            f"{error_body}"
        )

    try:

        data = response.json()

    except Exception:

        raise RuntimeError(
            "Binance TH returned invalid JSON"
        )

    # Binance TH normally uses code 0 for success.
    if isinstance(data, dict):

        code = data.get("code")

        if (
            code is not None
            and code != 0
        ):

            raise RuntimeError(
                "Binance TH API error: "
                f"{data}"
            )

    return data


# =========================================================
# ACCOUNT INFORMATION
# Binance TH:
# GET /api/v1/accountV2
# =========================================================

def get_account():

    return signed_get(
        "/api/v1/accountV2"
    )


# =========================================================
# PUBLIC PRICES
# Binance TH:
# GET /api/v1/ticker/price
# =========================================================

def get_all_prices():

    response = requests.get(
        f"{BINANCE_API_URL}/api/v1/ticker/price",
        timeout=15
    )

    response.raise_for_status()

    data = response.json()

    prices = {}

    # Binance TH can return an array
    # when symbol is omitted.
    if isinstance(data, list):

        items = data

    elif isinstance(data, dict):

        items = [data]

    else:

        return prices

    for item in items:

        symbol = item.get(
            "symbol"
        )

        price = item.get(
            "price"
        )

        if not symbol or price is None:
            continue

        try:

            prices[symbol] = float(
                price
            )

        except (
            TypeError,
            ValueError
        ):

            continue

    return prices


# =========================================================
# PORTFOLIO
# =========================================================

def get_portfolio():

    account = get_account()

    balances = account.get(
        "balances",
        []
    )

    prices = get_all_prices()

    portfolio = []

    total_usdt = 0.0

    for balance in balances:

        asset = balance.get(
            "asset"
        )

        if not asset:
            continue

        try:

            free = float(
                balance.get(
                    "free",
                    0
                )
            )

            locked = float(
                balance.get(
                    "locked",
                    0
                )
            )

        except (
            TypeError,
            ValueError
        ):

            continue

        total = (
            free + locked
        )

        # Ignore zero balances.
        if total <= 0:
            continue

        # -------------------------------------------------
        # USDT
        # -------------------------------------------------

        if asset == "USDT":

            price_usdt = 1.0

        else:

            symbol = (
                f"{asset}USDT"
            )

            price_usdt = prices.get(
                symbol
            )

        # -------------------------------------------------
        # Value
        # -------------------------------------------------

        if price_usdt is not None:

            value_usdt = (
                total
                * price_usdt
            )

            total_usdt += value_usdt

        else:

            value_usdt = None

        portfolio.append(
            {
                "asset": asset,
                "free": free,
                "locked": locked,
                "total": total,
                "price_usdt": (
                    round(
                        price_usdt,
                        12
                    )
                    if price_usdt is not None
                    else None
                ),
                "value_usdt": (
                    round(
                        value_usdt,
                        8
                    )
                    if value_usdt is not None
                    else None
                )
            }
        )

    # Highest-value assets first.
    portfolio.sort(
        key=lambda item: (
            item["value_usdt"]
            if item["value_usdt"] is not None
            else 0
        ),
        reverse=True
    )

    return {
        "status": "success",
        "account_type": "READ_ONLY",
        "total_value_usdt": round(
            total_usdt,
            8
        ),
        "assets": portfolio
    }
