import requests


COINS=[
    "BTCUSDT",
    "ETHUSDT",
    "XRPUSDT"
]



def get_market():

    result={}


    for symbol in COINS:


        url=(
        "https://api.binance.com/api/v3/klines"
        f"?symbol={symbol}"
        "&interval=1h"
        "&limit=50"
        )


        response=requests.get(
            url,
            timeout=10
        )


        candles=response.json()


        prices=[
            float(c[4])
            for c in candles
        ]


        result[
            symbol.replace(
                "USDT",
                ""
            )
        ] = {

            "price":prices[-1],

            "prices":prices

        }


    return result
