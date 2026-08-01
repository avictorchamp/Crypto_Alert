import requests
import time


CACHE = {}
CACHE_TIME = 300


COINCAP_URL = (
    "https://api.coincap.io/v2/assets"
)


COINS = {
    "XRP": "xrp",
    "ETH": "ethereum"
}


def get_price(asset):

    now = time.time()


    if asset in CACHE:

        old = CACHE[asset]

        if now - old["time"] < CACHE_TIME:
            return old["price"]


    response = requests.get(
        COINCAP_URL,
        params={
            "ids": asset
        },
        timeout=10
    )


    data = response.json()


    price = float(
        data["data"][0]["priceUsd"]
    )


    CACHE[asset] = {
        "price": price,
        "time": now
    }


    return price



def get_market():

    return {

        "XRP": get_price("xrp"),

        "ETH": get_price("ethereum")

    }
