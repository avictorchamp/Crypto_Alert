import os
import time
import hmac
import hashlib
import requests
from urllib.parse import urlencode


BINANCE_API_URL = "https://api.binance.com"
RECV_WINDOW = 10000


def get_credentials():
    api_key = os.getenv("BINANCE_API_KEY")
    api_secret = os.getenv("BINANCE_API_SECRET")

    if not api_key:
        raise RuntimeError(
            "BINANCE_API_KEY is missing"
        )

    if not api_secret:
        raise RuntimeError(
            "BINANCE_API_SECRET is missing"
        )

    # Remove accidental whitespace.
    return (
        api_key.strip(),
        api_secret.strip()
    )


def get_server_time():

    response = requests.get(
        f"{BINANCE_API_URL}/api/v3/time",
        timeout=10
    )

    response.raise_for_status()

    data = response.json()

    return int(
        data["serverTime"]
    )


def signed_get(path, params=None):

    api_key, api_secret = get_credentials()

    params = dict(
        params or {}
    )

    # Use Binance server time instead of Render's
    # local clock.
    params["timestamp"] = (
        get_server_time()
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

    signed_query = (
        f"{query_string}"
        f"&signature={signature}"
    )

    url = (
        f"{BINANCE_API_URL}"
        f"{path}"
        f"?{signed_query}"
    )

    headers = {
        "X-MBX-APIKEY": api_key
    }

    response = requests.get(
        url,
        headers=headers,
        timeout=15
    )

    # -----------------------------------------------------
    # IMPORTANT:
    # Return Binance's actual response instead of hiding it.
    # -----------------------------------------------------

    if response.status_code != 200:

        try:
            error_body = response.json()
        except Exception:
            error_body = {
                "raw": response.text
            }

        raise RuntimeError(
            "Binance API error "
            f"HTTP {response.status_code}: "
            f"{error_body}"
        )

    return response.json()


def get_account():

    return signed_get(
        "/api/v3/account"
    )


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

        if total <= 0:
            continue

        if asset == "USDT":

            price_usdt = 1.0

        else:

            price_usdt = prices.get(
                f"{asset}USDT"
            )

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
                "price_usdt": price_usdt,
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
