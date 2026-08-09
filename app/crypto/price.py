import requests
import time


# =========================================================
# CRYPTO ALERT V3.2
# DYNAMIC TOP 50 MARKET SCANNER
# =========================================================

BINANCE_24HR_URL = (
    "https://api.binance.com/api/v3/ticker/24hr"
)

BINANCE_KLINES_URL = (
    "https://api.binance.com/api/v3/klines"
)

KLINE_INTERVAL = "1h"
KLINE_LIMIT = 50

# Refresh the candidate universe every 30 minutes.
# Actual price/indicator scan is still performed every 5 minutes
# by the scheduler in main.py.
UNIVERSE_REFRESH_SECONDS = 1800

TOP_N = 50


# =========================================================
# EXCLUSIONS
# =========================================================

STABLECOINS = {
    "USDT",
    "USDC",
    "FDUSD",
    "TUSD",
    "USDP",
    "DAI",
    "PYUSD",
    "BUSD",
    "EUR",
    "TRY",
    "BRL",
    "GBP",
    "AUD",
    "BIDR",
    "UAH",
    "RUB",
}

# Avoid leveraged / synthetic / special Binance tokens.
LEVERAGED_PREFIXES = (
    "UP",
    "DOWN",
    "BULL",
    "BEAR",
)

LEVERAGED_SUFFIXES = (
    "UP",
    "DOWN",
    "BULL",
    "BEAR",
)


# =========================================================
# CACHE
# =========================================================

_cached_symbols = []
_cached_at = 0.0


# =========================================================
# HELPERS
# =========================================================

def is_valid_symbol(symbol):

    if not symbol.endswith("USDT"):
        return False

    base = symbol[:-4]

    if not base:
        return False

    if base in STABLECOINS:
        return False

    for prefix in LEVERAGED_PREFIXES:

        if base.startswith(prefix):
            return False

    for suffix in LEVERAGED_SUFFIXES:

        if base.endswith(suffix):
            return False

    return True


# =========================================================
# DYNAMIC TOP 50
# =========================================================

def get_top_symbols():

    global _cached_symbols
    global _cached_at

    now = time.time()

    # Use cached universe when still valid.
    if (
        _cached_symbols
        and
        now - _cached_at
        < UNIVERSE_REFRESH_SECONDS
    ):

        return list(_cached_symbols)

    try:

        response = requests.get(
            BINANCE_24HR_URL,
            timeout=15
        )

        response.raise_for_status()

        tickers = response.json()

        if not isinstance(tickers, list):

            raise ValueError(
                "Invalid Binance 24hr ticker response"
            )

        candidates = []

        for ticker in tickers:

            symbol = ticker.get(
                "symbol"
            )

            if not symbol:
                continue

            if not is_valid_symbol(
                symbol
            ):
                continue

            try:

                quote_volume = float(
                    ticker.get(
                        "quoteVolume",
                        0
                    )
                )

            except (
                TypeError,
                ValueError
            ):

                continue

            if quote_volume <= 0:
                continue

            candidates.append(
                (
                    symbol,
                    quote_volume
                )
            )

        # Highest USDT quote volume first.
        candidates.sort(
            key=lambda x: x[1],
            reverse=True
        )

        symbols = [
            item[0]
            for item in candidates[:TOP_N]
        ]

        if not symbols:

            raise ValueError(
                "No valid dynamic symbols found"
            )

        _cached_symbols = symbols
        _cached_at = now

        print(
            "Dynamic Top 50 refreshed:"
        )

        print(
            ", ".join(symbols)
        )

        return list(symbols)

    except Exception as e:

        print(
            f"Top 50 refresh error: {e}"
        )

        # If Binance temporarily fails,
        # keep using the previous universe.
        if _cached_symbols:

            print(
                "Using previous cached Top 50."
            )

            return list(
                _cached_symbols
            )

        return []


# =========================================================
# GET MARKET DATA
# =========================================================

def get_market():

    result = {}

    symbols = get_top_symbols()

    if not symbols:

        return result

    for symbol in symbols:

        try:

            response = requests.get(
                BINANCE_KLINES_URL,
                params={
                    "symbol": symbol,
                    "interval": KLINE_INTERVAL,
                    "limit": KLINE_LIMIT
                },
                timeout=10
            )

            response.raise_for_status()

            candles = response.json()

            if not isinstance(
                candles,
                list
            ):

                print(
                    f"Invalid candles for {symbol}"
                )

                continue

            if len(candles) < KLINE_LIMIT:

                print(
                    f"Not enough candles for {symbol}: "
                    f"{len(candles)}"
                )

                continue

            prices = []

            for candle in candles:

                try:

                    prices.append(
                        float(candle[4])
                    )

                except (
                    TypeError,
                    ValueError,
                    IndexError
                ):

                    pass

            if len(prices) < KLINE_LIMIT:

                print(
                    f"Invalid price data for {symbol}"
                )

                continue

            coin = symbol[:-4]

            result[coin] = {
                "price": prices[-1],
                "prices": prices
            }

        except requests.RequestException as e:

            print(
                f"Market request error "
                f"for {symbol}: {e}"
            )

        except (
            ValueError,
            TypeError,
            IndexError
        ) as e:

            print(
                f"Market parse error "
                f"for {symbol}: {e}"
            )

        except Exception as e:

            print(
                f"Unexpected market error "
                f"for {symbol}: {e}"
            )

    print(
        f"Market scan completed: "
        f"{len(result)} coins"
    )

    return result
