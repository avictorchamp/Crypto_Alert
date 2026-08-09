import requests


# =========================================================
# CRYPTO ALERT V3.2
# TOP 20 LIQUID CRYPTO
# =========================================================

COINS = [
    "BTCUSDT",
    "ETHUSDT",
    "BNBUSDT",
    "SOLUSDT",
    "XRPUSDT",
    "DOGEUSDT",
    "ADAUSDT",
    "AVAXUSDT",
    "LINKUSDT",
    "SUIUSDT",
    "TRXUSDT",
    "DOTUSDT",
    "LTCUSDT",
    "BCHUSDT",
    "UNIUSDT",
    "ATOMUSDT",
    "NEARUSDT",
    "APTUSDT",
    "FILUSDT",
    "ETCUSDT",
]


BINANCE_URL = (
    "https://api.binance.com/api/v3/klines"
)


def get_market():

    result = {}

    for symbol in COINS:

        try:

            url = (
                f"{BINANCE_URL}"
                f"?symbol={symbol}"
                "&interval=1h"
                "&limit=50"
            )

            response = requests.get(
                url,
                timeout=10
            )

            response.raise_for_status()

            candles = response.json()

            # Binance can return an error object
            if not isinstance(candles, list):
                print(
                    f"Market data invalid for {symbol}: "
                    f"{candles}"
                )
                continue

            if len(candles) < 50:
                print(
                    f"Not enough candles for {symbol}: "
                    f"{len(candles)}"
                )
                continue

            prices = [
                float(candle[4])
                for candle in candles
            ]

            coin = symbol.replace(
                "USDT",
                ""
            )

            result[coin] = {
                "price": prices[-1],
                "prices": prices
            }

        except requests.RequestException as e:

            print(
                f"Market request error for {symbol}: {e}"
            )

        except (ValueError, TypeError, IndexError) as e:

            print(
                f"Market data parse error for {symbol}: {e}"
            )

        except Exception as e:

            print(
                f"Unexpected market error for {symbol}: {e}"
            )

    return result
