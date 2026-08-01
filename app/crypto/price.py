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

    if "price" not in data:
        raise Exception(
            f"Binance Error: {data}"
        )

    return float(data["price"])



def get_market():

    return {
        "XRP": get_price("XRPUSDT"),
        "ETH": get_price("ETHUSDT")
    }
