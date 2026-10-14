"""Crypto Alert market engine v3.11.0.
Dynamic Top 50 + Watchlist Memory monitoring. READ ONLY.
"""
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.crypto.watchlist_memory import get_watchlist

VERSION = "3.11.0"
# Prefer Binance's dedicated public market-data host, then fall back to
# the standard and alternate API hosts if a region/IP is blocked.
BINANCE_MARKET_BASES = (
    "https://data-api.binance.vision",
    "https://api.binance.com",
    "https://api1.binance.com",
    "https://api2.binance.com",
    "https://api3.binance.com",
)
BINANCE_24HR_PATH = "/api/v3/ticker/24hr"
BINANCE_KLINES_PATH = "/api/v3/klines"
BYBIT_BASE_URL = "https://api.bybit.com"
BYBIT_TICKERS_PATH = "/v5/market/tickers"
BYBIT_KLINES_PATH = "/v5/market/kline"
KLINE_INTERVAL = "1h"
KLINE_LIMIT = 100
MAX_WORKERS = 8
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


def get_json_with_fallback(path, params=None, timeout=15):
    """Fetch public market data with endpoint failover.

    Render egress IPs can receive HTTP 418 from api.binance.com. The
    dedicated market-data endpoint and alternate Binance API hosts are
    tried in order so one blocked hostname does not disable the scanner.
    """
    errors = []
    for base in BINANCE_MARKET_BASES:
        try:
            response = requests.get(
                f"{base}{path}",
                params=params,
                timeout=timeout,
            )
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            errors.append(f"{base}: {exc}")
            # Binance explicitly asks clients to back off after 418/429.
            # Do not keep hitting alternate Binance hosts from the same IP.
            status_code = getattr(response, "status_code", None) if "response" in locals() else None
            if status_code in (418, 429):
                break
    raise RuntimeError(
        "All Binance market-data endpoints failed: " + " | ".join(errors)
    )


def get_bybit_json(path, params=None, timeout=15):
    """Read public Bybit spot market data when Binance is IP-banned."""
    response = requests.get(
        f"{BYBIT_BASE_URL}{path}",
        params=params,
        timeout=timeout,
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict) or data.get("retCode") != 0:
        raise RuntimeError(f"Bybit market-data API error: {data}")
    return data


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
        try:
            tickers = get_json_with_fallback(BINANCE_24HR_PATH, timeout=15)
        except Exception as binance_error:
            print(f"Binance market data unavailable; using Bybit spot tickers: {binance_error}")
            bybit = get_bybit_json(
                BYBIT_TICKERS_PATH,
                params={"category": "spot"},
                timeout=15,
            )
            tickers = bybit.get("result", {}).get("list", [])
        if not isinstance(tickers, list):
            raise ValueError("Invalid market ticker response")
        candidates = []
        for ticker in tickers:
            if not isinstance(ticker, dict):
                continue
            symbol = ticker.get("symbol")
            if not symbol or not is_valid_symbol(symbol):
                continue
            try:
                volume = float(ticker.get("quoteVolume", ticker.get("turnover24h", 0)))
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
    combined = list(dict.fromkeys(dynamic + extra + ["XRPUSDT"]))
    return dynamic, extra, combined


def get_symbol_market_data(symbol):
    try:
        candles = get_json_with_fallback(
            BINANCE_KLINES_PATH,
            params={"symbol": symbol, "interval": KLINE_INTERVAL, "limit": KLINE_LIMIT},
            timeout=8,
        )
    except Exception as binance_error:
        print(f"Binance candles unavailable for {symbol}; using Bybit spot candles: {binance_error}")
        bybit = get_bybit_json(
            BYBIT_KLINES_PATH,
            params={
                "category": "spot",
                "symbol": symbol,
                "interval": "60",
                "limit": KLINE_LIMIT,
            },
            timeout=8,
        )
        # Bybit returns candles newest-first; this engine expects oldest-first.
        candles = list(reversed(bybit.get("result", {}).get("list", [])))
    if not isinstance(candles, list) or len(candles) < KLINE_LIMIT:
        raise ValueError(f"Not enough candles for {symbol}")

    closes = []
    volumes = []
    for candle in candles:
        try:
            closes.append(float(candle[4]))
            volumes.append(float(candle[5]))
        except (TypeError, ValueError, IndexError):
            continue

    if len(closes) < KLINE_LIMIT or len(volumes) < KLINE_LIMIT:
        raise ValueError(f"Invalid market data for {symbol}")

    price = closes[-1]
    avg_volume = sum(volumes[-21:-1]) / 20
    volume_ratio = volumes[-1] / avg_volume if avg_volume > 0 else None
    momentum_6h = (price / closes[-7]) - 1 if len(closes) >= 7 and closes[-7] else None

    coin = symbol[:-4]
    return coin, {
        "symbol": symbol,
        "coin": coin,
        "price": price,
        "prices": closes,
        "volumes": volumes,
        "volume_ratio": volume_ratio,
        "momentum_6h": momentum_6h,
    }


def get_market():
    global _last_market_status
    started = time.time()
    result = {}
    failed = []
    dynamic, extra, symbols = get_monitor_symbols()
    print(f"Market universe: Top50={len(dynamic)}, WatchlistExtra={len(extra)}, Total={len(symbols)}")
    if extra:
        print("Watchlist extra:", ", ".join(x[:-4] for x in extra))
    # Fetch candles concurrently. The scanner runs every 5 minutes; serially
    # fetching 50 symbols can exceed that interval when Binance is slow.
    # A bounded pool keeps latency predictable without creating an excessive
    # request burst.
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(get_symbol_market_data, symbol): symbol for symbol in symbols}
        for future in as_completed(futures):
            symbol = futures[future]
            try:
                coin, data = future.result()
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
