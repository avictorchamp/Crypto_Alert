import requests


BINANCE_URL = "https://api.binance.com/api/v3/ticker/price"


def get_price(symbol):

    response = requests.get(
        BINANCE_URL,
        params={
            "symbol": symbol
        },
        timeout=10
    )

    data = response.json()

    return float(data["price"])


def get_market():

    return {
        "XRP": get_price("XRPUSDT"),
        "ETH": get_price("ETHUSDT")
    }
