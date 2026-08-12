"""
Crypto Alert Backtest Engine v1.1.0

READ-ONLY research tool. Does not access Binance account APIs and never places orders.

Compares:
  A) CURRENT: production-style RSI/EMA/support/resistance entry logic
  B) SCORE: hard risk filters + entry score + reversal confirmation

Historical research data comes from Coinbase Exchange public 1H candles.
This avoids Binance global API geographic restrictions in GitHub Actions.

Usage:
    python backtest.py --months 12
    python backtest.py --months 24 --coins BTC ETH XRP SOL BNB ADA DOGE LINK AVAX
"""

import argparse
import math
import statistics
import time
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta

import requests

BASE_URL = "https://api.exchange.coinbase.com/products/{product}/candles"
GRANULARITY = 3600
MAX_CANDLES_PER_REQUEST = 300
DEFAULT_COINS = ["BTC", "ETH", "XRP", "SOL", "BNB", "ADA", "DOGE", "LINK", "AVAX"]
FEE_RATE = 0.001
SLIPPAGE_RATE = 0.0005
INITIAL_EQUITY = 1000.0
MAX_HOLD_BARS = 72
MIN_RR = 1.0
MIN_QUALITY = 70.0
REQUEST_TIMEOUT = 30


@dataclass
class Trade:
    coin: str
    strategy: str
    entry_time: int
    exit_time: int
    entry: float
    exit: float
    stop: float
    target: float
    r_multiple: float
    pnl_pct: float
    bars: int
    reason: str


def utc_from_ms(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def fetch_klines(coin, months):
    """Download 1H candles from Coinbase in <=300-candle chunks."""
    product = f"{coin}-USD"
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=months * 30.4375)
    cursor = start
    rows = []
    session = requests.Session()
    session.headers.update({"User-Agent": "Crypto-Alert-Backtest/1.1"})

    while cursor < end:
        chunk_end = min(cursor + timedelta(seconds=GRANULARITY * MAX_CANDLES_PER_REQUEST), end)
        params = {
            "start": cursor.isoformat().replace("+00:00", "Z"),
            "end": chunk_end.isoformat().replace("+00:00", "Z"),
            "granularity": GRANULARITY,
        }
        response = session.get(BASE_URL.format(product=product), params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        batch = response.json()
        if not isinstance(batch, list):
            raise RuntimeError(f"Unexpected Coinbase response: {batch}")
        rows.extend(batch)
        if not batch:
            cursor = chunk_end
        else:
            max_ts = max(int(x[0]) for x in batch)
            next_cursor = datetime.fromtimestamp(max_ts + GRANULARITY, tz=timezone.utc)
            cursor = max(chunk_end, next_cursor)
        time.sleep(0.12)

    dedup = {int(x[0]): x for x in rows}
    candles = []
    for ts in sorted(dedup):
        x = dedup[ts]
        candles.append({
            "time": int(x[0]) * 1000,
            "open": float(x[3]),
            "high": float(x[2]),
            "low": float(x[1]),
            "close": float(x[4]),
            "volume": float(x[5]),
        })
    return candles


def ema(values, period):
    if len(values) < period:
        return None
    m = 2.0 / (period + 1.0)
    value = values[0]
    for v in values[1:]:
        value = v * m + value * (1.0 - m)
    return value


def rsi(values, period=14):
    if len(values) <= period:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(values)):
        d = values[i] - values[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    ag = sum(gains[-period:]) / period
    al = sum(losses[-period:]) / period
    if al == 0:
        return 100.0
    return 100.0 - 100.0 / (1.0 + ag / al)


def indicators(history):
    closes = [x["close"] for x in history]
    if len(closes) < 50:
        return None
    price = closes[-1]
    e20 = ema(closes, 20)
    e50 = ema(closes, 50)
    rv = rsi(closes, 14)
    support = min(closes[-50:])
    resistance = max(closes[-50:])
    if e20 is None or e50 is None:
        return None
    entry_low = support
    entry_high = support * 1.005
    stop = support * 0.99
    target = resistance
    risk = price - stop
    reward = target - price
    rr = reward / risk if risk > 0 else 0.0
    return {
        "price": price, "ema20": e20, "ema50": e50, "rsi": rv,
        "support": support, "resistance": resistance,
        "entry_low": entry_low, "entry_high": entry_high,
        "stop": stop, "target": target, "rr": rr,
    }


def quality(ind):
    score = 0.0
    if ind["ema20"] > ind["ema50"]: score += 25
    if ind["price"] <= ind["support"] * 1.01: score += 20
    if ind["rsi"] < 65: score += 15
    if ind["rr"] >= 1: score += 20
    if ind["entry_low"] <= ind["price"] <= ind["entry_high"]: score += 20
    return score


def current_strategy(ind):
    q = quality(ind)
    in_entry = ind["entry_low"] <= ind["price"] <= ind["entry_high"]
    buy = (
        ind["ema20"] > ind["ema50"]
        and ind["price"] <= ind["support"] * 1.01
        and ind["rsi"] < 65
        and ind["rr"] >= MIN_RR
        and q >= MIN_QUALITY
        and in_entry
    )
    return buy, q


def score_strategy(ind, history):
    score = 0
    if ind["rsi"] <= 30: score += 20
    elif ind["rsi"] <= 35: score += 12
    if ind["price"] <= ind["support"] * 1.01: score += 20
    if ind["entry_low"] <= ind["price"] <= ind["entry_high"]: score += 20
    if ind["ema20"] > ind["ema50"]:
        score += 15
    else:
        prev = indicators(history[:-1])
        if prev and ind["ema20"] > prev["ema20"] and ind["ema50"] >= prev["ema50"]:
            score += 12
    closes = [x["close"] for x in history]
    if len(closes) >= 6 and closes[-1] > closes[-2] > closes[-3]: score += 15
    if ind["rr"] >= 2: score += 10
    elif ind["rr"] >= 1: score += 5
    q = quality(ind)
    return q >= MIN_QUALITY and ind["rr"] >= MIN_RR and score >= 70, q, score


def simulate(candles, coin, strategy_name):
    trades = []
    i = 50
    while i < len(candles) - 2:
        history = candles[:i + 1]
        ind = indicators(history)
        if not ind:
            i += 1
            continue
        result = current_strategy(ind) if strategy_name == "CURRENT" else score_strategy(ind, history)
        if not result[0]:
            i += 1
            continue

        entry_bar = candles[i + 1]
        entry = entry_bar["open"] * (1 + SLIPPAGE_RATE)
        stop = ind["stop"]
        target = ind["target"]
        risk = entry - stop
        if risk <= 0 or target <= entry:
            i += 1
            continue

        exit_index = min(i + 1 + MAX_HOLD_BARS, len(candles) - 1)
        exit_price = None
        exit_time = None
        reason = "TIME"
        for j in range(i + 1, exit_index + 1):
            bar = candles[j]
            if bar["low"] <= stop:
                exit_price = stop * (1 - SLIPPAGE_RATE)
                exit_time = bar["time"]
                reason = "SL"
                exit_index = j
                break
            if bar["high"] >= target:
                exit_price = target * (1 - SLIPPAGE_RATE)
                exit_time = bar["time"]
                reason = "TP"
                exit_index = j
                break
        if exit_price is None:
            bar = candles[exit_index]
            exit_price = bar["close"] * (1 - SLIPPAGE_RATE)
            exit_time = bar["time"]

        gross = (exit_price - entry) / entry
        net = gross - (2 * FEE_RATE)
        r = (exit_price - entry) / risk
        trades.append(Trade(
            coin, strategy_name, entry_bar["time"], exit_time, entry, exit_price,
            stop, target, r, net * 100, exit_index - (i + 1), reason
        ))
        i = exit_index + 1
    return trades


def metrics(trades):
    if not trades:
        return {"trades": 0, "win_rate_pct": 0, "profit_factor": 0, "expectancy_pct": 0,
                "average_r": 0, "max_drawdown_pct": 0, "net_return_pct": 0}
    wins = [t for t in trades if t.pnl_pct > 0]
    losses = [t for t in trades if t.pnl_pct <= 0]
    gross_win = sum(t.pnl_pct for t in wins)
    gross_loss = abs(sum(t.pnl_pct for t in losses))
    pf = gross_win / gross_loss if gross_loss else float("inf")
    equity = INITIAL_EQUITY
    peak = equity
    max_dd = 0.0
    for t in trades:
        equity *= 1 + t.pnl_pct / 100
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak * 100)
    return {
        "trades": len(trades),
        "win_rate_pct": round(len(wins) / len(trades) * 100, 2),
        "profit_factor": round(pf, 3) if math.isfinite(pf) else "INF",
        "expectancy_pct": round(statistics.mean(t.pnl_pct for t in trades), 4),
        "average_r": round(statistics.mean(t.r_multiple for t in trades), 4),
        "max_drawdown_pct": round(max_dd, 2),
        "net_return_pct": round((equity / INITIAL_EQUITY - 1) * 100, 2),
    }


def print_report(results, months):
    print("\n=== CRYPTO ALERT BACKTEST v1.1.0 ===")
    print(f"Period: approximately {months} months | Timeframe: 1H")
    print("Data: Coinbase Exchange public candles (USD pairs)")
    print(f"Fees: {FEE_RATE*100:.2f}% per side | Slippage: {SLIPPAGE_RATE*100:.2f}% per side")
    if not results:
        print("NO RESULTS: historical data could not be downloaded.")
        return
    aggregate = {}
    for coin, by_strategy in results.items():
        print(f"\n--- {coin} ---")
        for name, data in by_strategy.items():
            m = data["metrics"]
            aggregate.setdefault(name, []).extend(data["trades"])
            print(f"{name:>8}: trades={m['trades']:<4} win={m['win_rate_pct']:>6}% PF={m['profit_factor']} expectancy={m['expectancy_pct']}% avgR={m['average_r']} DD={m['max_drawdown_pct']}% return={m['net_return_pct']}%")
    print("\n=== AGGREGATE TRADE POOL ===")
    for name, trades in aggregate.items():
        print(f"{name:>8}: {metrics(trades)}")
    print("\nInterpretation: do NOT deploy from one metric alone. Require enough trades, PF > 1 after costs, acceptable drawdown, and stability across coins/regimes.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--months", type=int, default=12)
    parser.add_argument("--coins", nargs="+", default=DEFAULT_COINS)
    args = parser.parse_args()
    results = {}
    for coin in args.coins:
        coin = coin.upper()
        print(f"Downloading {coin} {args.months} months of 1H data from Coinbase...")
        try:
            candles = fetch_klines(coin, args.months)
            if len(candles) < 100:
                print(f"{coin}: insufficient candles ({len(candles)})")
                continue
            a = simulate(candles, coin, "CURRENT")
            b = simulate(candles, coin, "SCORE")
            results[coin] = {"CURRENT": {"metrics": metrics(a), "trades": a}, "SCORE": {"metrics": metrics(b), "trades": b}}
            print(f"{coin}: {len(candles)} candles loaded ({utc_from_ms(candles[0]['time']).date()} to {utc_from_ms(candles[-1]['time']).date()})")
        except Exception as exc:
            print(f"{coin}: ERROR: {exc}")
    print_report(results, args.months)


if __name__ == "__main__":
    main()
