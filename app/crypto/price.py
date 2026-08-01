import requests
from app.crypto.cache import cache_get, cache_set


COINS = [
    "BTCUSDT",
    "ETHUSDT",
    "BNBUSDT",
    "SOLUSDT",
    "XRPUSDT"
]


def get_market():

    cache = cache_get("market")

    if cache:
        return cache


    result = {}

    for symbol in COINS:

        url = (
            "https://api.binance.com/api/v3/ticker/price"
            f"?symbol={symbol}"
        )


        r = requests.get(
            url,
            timeout=10
        )

        data = r.json()


        if "price" in data:

            coin = symbol.replace(
                "USDT",
                ""
            )

            result[coin] = float(
                data["price"]
            )


    cache_set(
        "market",
        result
    )


    return result
