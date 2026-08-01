import requests

from app.crypto.cache import (
    get_cache,
    set_cache
)


BINANCE_URL = (
    "https://api.binance.com/api/v3/ticker/price"
)


COINGECKO_URL = (
    "https://api.coingecko.com/api/v3/simple/price"
)



COINS = {

    "BTC": {
        "binance": "BTCUSDT",
        "coingecko": "bitcoin"
    },

    "ETH": {
        "binance": "ETHUSDT",
        "coingecko": "ethereum"
    },

    "XRP": {
        "binance": "XRPUSDT",
        "coingecko": "xrp"
    }

}



def get_binance_price(symbol):

    try:

        r = requests.get(
            BINANCE_URL,
            params={
                "symbol": symbol
            },
            timeout=5
        )


        data = r.json()


        if "price" in data:
            return float(data["price"])


    except Exception:

        return None



def get_coingecko_price(coin):

    try:

        r = requests.get(
            COINGECKO_URL,
            params={
                "ids": coin,
                "vs_currencies": "usd"
            },
            timeout=5
        )


        data = r.json()


        if coin in data:
            return float(
                data[coin]["usd"]
            )


    except Exception:

        return None



def get_price(name):


    cached = get_cache(name)


    if cached:
        return cached



    config = COINS[name]


    price = get_binance_price(
        config["binance"]
    )


    source = "binance"



    if price is None:

        price = get_coingecko_price(
            config["coingecko"]
        )

        source = "coingecko"



    if price is None:

        raise Exception(
            f"Unable to get price {name}"
        )


    result = {

        "price": price,

        "source": source

    }


    set_cache(
        name,
        result
    )


    return result



def get_market():


    market = {}


    for coin in COINS:

        data = get_price(
            coin
        )


        market[coin] = data["price"]



    return market
