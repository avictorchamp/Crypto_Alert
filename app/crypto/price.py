import requests


CRYPTOCOMPARE_URL = (
    "https://min-api.cryptocompare.com/data/pricemulti"
)


def get_market():

    response = requests.get(
        CRYPTOCOMPARE_URL,
        params={
            "fsyms": "XRP,ETH",
            "tsyms": "USD"
        },
        timeout=10
    )


    data = response.json()


    if "XRP" not in data or "ETH" not in data:
        raise Exception(
            f"CryptoCompare Error: {data}"
        )


    return {

        "XRP": float(
            data["XRP"]["USD"]
        ),

        "ETH": float(
            data["ETH"]["USD"]
        )

    }
