import requests


def get_price(coin):

    url = "https://api.coingecko.com/api/v3/simple/price"

    params = {
        "ids": coin,
        "vs_currencies": "usd"
    }


    r = requests.get(
        url,
        params=params,
        timeout=10
    )


    data = r.json()

    return float(
        data[coin]["usd"]
    )



def get_market():

    return {

        "XRP": get_price("ripple"),

        "ETH": get_price("ethereum")

    }
