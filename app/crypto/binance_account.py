import os
import time
import hmac
import hashlib
import requests
from urllib.parse import urlencode


BINANCE_API_URL = "https://api.binance.com"

API_KEY_ENV = "BINANCE_API_KEY"
API_SECRET_ENV = "BINANCE_API_SECRET"

RECV_WINDOW = 5000


# =========================================================
# CONFIG
# =========================================================

def get_credentials():

    api_key = os.getenv(
        API_KEY_ENV
    )

    api_secret = os.getenv(
        API_SECRET_ENV
    )

    if not api_key:
        raise RuntimeError(
            "BINANCE_API_KEY is not configured"
        )

    if not api_secret:
        raise RuntimeError(
            "BINANCE_API_SECRET is not configured"
        )

    return api_key, api_secret


# =========================================================
# SIGNED REQUEST
# =========================================================

def signed_get(
    path,
    params=None
):

    api_key, api_secret = get_credentials()

    params = params or {}

    params["timestamp"] = int(
        time.time() * 1000
    )

    params["recvWindow"] = RECV_WINDOW

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
        "X-MBX-APIKEY": api_key
    }

    response = requests.get(
        f"{BINANCE_API_URL}{path}",
        params=params,
        headers=headers,
        timeout=15
    )

    response.raise_for_status()

    return response.json()


# =========================================================
# ACCOUNT
# =========================================================

def get_account():

    return signed_get(
        "/api/v3/account"
    )


# =========================================================
# PUBLIC PRICES
# =========================================================

def get_all_prices():

    response = requests.get(
        f"{BINANCE_API_URL}/api/v3/ticker/price",
        timeout=15
    )

    response.raise_for_status()

    data = response.json()

    prices = {}

    for item in data:

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

        free = balance.get(
            "free",
            "0"
        )

        locked = balance.get(
            "locked",
            "0"
        )

        try:

            free_amount = float(
                free
            )

            locked_amount = float(
                locked
            )

        except (
            TypeError,
            ValueError
        ):

            continue

        total_amount = (
            free_amount
            + locked_amount
        )

        # Ignore dust / zero balances.
        if total_amount <= 0:
            continue

        # -------------------------------------------------
        # USDT
        # -------------------------------------------------

        if asset == "USDT":

            usdt_price = 1.0

            usdt_value = total_amount

        else:

            symbol = (
                f"{asset}USDT"
            )

            usdt_price = prices.get(
                symbol
            )

            if usdt_price is None:

                usdt_value = None

            else:

                usdt_value = (
                    total_amount
                    * usdt_price
                )

        if usdt_value is not None:

            total_usdt += usdt_value

        portfolio.append(
            {
                "asset": asset,
                "free": free_amount,
                "locked": locked_amount,
                "total": total_amount,
                "price_usdt": usdt_price,
                "value_usdt": (
                    round(
                        usdt_value,
                        8
                    )
                    if usdt_value is not None
                    else None
                )
            }
        )

    # Highest value first.
    portfolio.sort(
        key=lambda x: (
            x["value_usdt"]
            if x["value_usdt"] is not None
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
