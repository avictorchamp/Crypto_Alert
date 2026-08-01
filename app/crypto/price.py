import requests


COINGECKO_URL = (
    "https://api.coingecko.com/api/v3/simple/price"
)


def get_price(coin):

    response = requests.get(
        COINGECKO_URL,
        params={
            "ids": coin,
            "vs_currencies": "usd"
        },
        headers={
            "accept": "application/json"
        },
        timeout=10
    )


    data = response.json()


    if coin not in data:

        raise Exception(
            f"CoinGecko response error: {data}"
        )


    return float(
        data[coin]["usd"]
    )



def get_market():

    return {

        "XRP": get_price("xrp"),

        "ETH": get_price("ethereum")

    }
