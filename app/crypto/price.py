"""Crypto Alert market engine v3.10.0.
Dynamic Top 50 + Watchlist Memory monitoring. READ ONLY.
"""
import time
import requests

from app.crypto.watchlist_memory import get_watchlist

VERSION = "3.10.0"
BINANCE_24HR_URL = "https://api.binance.com/api/v3/ticker/24hr"
BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
KLINE_INTERVAL = "1h"
KLINE_LIMIT = 50
UNIVERSE_REFRESH_SECONDS = 1800
TOP_N = 50
MAX_WATCHLIST_EXTRA = 100

STABLECOINS = {
    "USDT", "USDC", "FDUSD", "TUSD", "USDP", "DAI", "PYUSD", "BUSD",
    "EUR", "TRY", "BRL", "GBP", "AUD", "BIDR", "UAH", "RUB",
}
LEVERAGED_PREFIXES = ("UP", "DOWN", "BULL", "BEAR")
LEVERAGED_SUFFIXES = ("UP", "DOWN", "BULL", "BEAR")

_cached_symbols = []
_cached_at = 0.0
_last_market_status = {"status": "NOT_STARTED"}


def normalize_coin(coin):
    return str(coin).upper().strip()


def coin_to_symbol(coin):
    coin = normalize_coin(coin)
    if not coin:
        return ""
    return coin if coin.endswith("USDT") else f"{coin}USDT"


def is_valid_symbol(symbol):
    symbol = normalize_coin(symbol)
    if not symbol.endswith("USDT"):
        return False
    base = symbol[:-4]
    if not base or base in STABLECOINS:
        return False
    if any(base.startswith(x) for x in LEVERAGED_PREFIXES):
        return False
    if any(base.endswith(x) for x in LEVERAGED_SUFFIXES):
        return False
    return True


def get_top_symbols():
    global _cached_symbols, _cached_at
    now = time.time()
    if _cached_symbols and now - _cached_at < UNIVERSE_REFRESH_SECONDS:
        return list(_cached_symbols)
    try:
        response = requests.get(BINANCE_24HR_URL, timeout=15)
        response.raise_for_status()
        tickers = response.json()
        if not isinstance(tickers, list):
            raise ValueError("Invalid Binance 24hr ticker response")
        candidates = []
        for ticker in tickers:
            if not isinstance(ticker, dict):
                continue
            symbol = ticker.get("symbol")
            if not symbol or not is_valid_symbol(symbol):
                continue
            try:
                volume = float(ticker.get("quoteVolume", 0))
            except (TypeError, ValueError):
                continue
            if volume > 0:
                candidates.append((normalize_coin(symbol), volume))
        candidates.sort(key=lambda x: x[1], reverse=True)
        symbols = [x[0] for x in candidates[:TOP_N]]
        if not symbols:
            raise ValueError("No valid dynamic symbols found")
        _cached_symbols, _cached_at = symbols, now
        print("Dynamic Top 50 refreshed:", ", ".join(symbols))
        return list(symbols)
    except Exception as e:
        print(f"Top 50 refresh error: {e}")
        if _cached_symbols:
            print("Using previous cached Top 50.")
            return list(_cached_symbols)
        return []


def get_watchlist_symbols(dynamic_symbols):
    dynamic = {normalize_coin(x) for x in dynamic_symbols}
    try:
        remembered = get_watchlist()
    except Exception as e:
        print(f"Watchlist memory read error: {e}")
        remembered = []
    extra = []
    for coin in remembered:
        symbol = coin_to_symbol(coin)
        if is_valid_symbol(symbol) and symbol not in dynamic:
            extra.append(symbol)
    return sorted(set(extra))[:MAX_WATCHLIST_EXTRA]


def get_monitor_symbols():
    dynamic = get_top_symbols()
    extra = get_watchlist_symbols(dynamic)
    combined = list(dict.fromkeys(dynamic + extra))
    return dynamic, extra, combined


def get_symbol_market_data(symbol):
    response = requests.get(
        BINANCE_KLINES_URL,
        params={"symbol": symbol, "interval": KLINE_INTERVAL, "limit": KLINE_LIMIT},
        timeout=10,
    )
    response.raise_for_status()
    candles = response.json()
    if not isinstance(candles, list) or len(candles) < KLINE_LIMIT:
        raise ValueError(f"Not enough candles for {symbol}")
    prices = []
    for candle in candles:
        try:
            prices.append(float(candle[4]))
        except (TypeError, ValueError, IndexError):
            continue
    if len(prices) < KLINE_LIMIT:
        raise ValueError(f"Invalid price data for {symbol}")
    coin = symbol[:-4]
    return coin, {"symbol": symbol, "coin": coin, "price": prices[-1], "prices": prices}


def get_market():
    global _last_market_status
    started = time.time()
    result = {}
    failed = []
    dynamic, extra, symbols = get_monitor_symbols()
    print(f"Market universe: Top50={len(dynamic)}, WatchlistExtra={len(extra)}, Total={len(symbols)}")
    if extra:
        print("Watchlist extra:", ", ".join(x[:-4] for x in extra))
    for symbol in symbols:
        try:
            coin, data = get_symbol_market_data(symbol)
            result[coin] = data
        except Exception as e:
            failed.append({"symbol": symbol, "error": str(e)})
            print(f"Market error for {symbol}: {e}")
    duration = round(time.time() - started, 3)
    _last_market_status = {
        "status": "success",
        "dynamic_count": len(dynamic),
        "watchlist_extra_count": len(extra),
        "total_symbols": len(symbols),
        "successful_count": len(result),
        "failed_count": len(failed),
        "duration_seconds": duration,
        "watchlist_extra": [x[:-4] for x in extra],
        "failed_symbols": failed[:20],
    }
    print(f"Market scan completed: {len(result)} coins in {duration}s")
    return result


def get_market_status():
    return dict(_last_market_status)


def refresh_universe():
    global _cached_symbols, _cached_at
    _cached_symbols = []
    _cached_at = 0.0
    return get_top_symbols()


def is_read_only():
    return True
