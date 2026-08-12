"""
Crypto Alert Backtest Engine v1.0.0

READ-ONLY research tool. Does not access Binance account APIs and never places orders.

Compares:
  A) Current production-style strategy using RSI/EMA/support/resistance
  B) Score-based reversal strategy: hard risk filters + entry score + confirmation

Usage:
    python backtest.py
    python backtest.py --months 12
    python backtest.py --months 24 --coins BTC ETH XRP SOL BNB ADA DOGE LINK AVAX

Historical market data is downloaded from Binance public market-data API only.
Results include fees and configurable slippage.
"""

import argparse
import math
import statistics
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import requests

BASE_URL = "https://api.binance.com/api/v3/klines"
INTERVAL = "1h"
DEFAULT_COINS = ["BTC", "ETH", "XRP", "SOL", "BNB", "ADA", "DOGE", "LINK", "AVAX"]
FEE_RATE = 0.001       # 0.10% per side
SLIPPAGE_RATE = 0.0005 # 0.05% per side
INITIAL_EQUITY = 1000.0
MAX_HOLD_BARS = 72      # 3 days on 1H data
MIN_RR = 1.0
MIN_QUALITY = 70.0


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


def fetch_klines(coin, months):
    symbol = f"{coin}USDT"
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - int(months * 30.4375 * 24 * 3600 * 1000)
    rows = []
    cursor = start_ms
    while cursor < end_ms:
        params = {
            "symbol": symbol,
            "interval": INTERVAL,
            "startTime": cursor,
            "endTime": end_ms,
            "limit": 1000,
        }
        r = requests.get(BASE_URL, params=params, timeout=20)
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        rows.extend(batch)
        last_open = int(batch[-1][0])
        next_cursor = last_open + 3600000
        if next_cursor <= cursor:
            break
        cursor = next_cursor
        if len(batch) < 1000:
            break
        time.sleep(0.05)
    dedup = {int(x[0]): x for x in rows}
    ordered = [dedup[k] for k in sorted(dedup)]
    candles = []
    for x in ordered:
        candles.append({
            "time": int(x[0]),
            "open": float(x[1]),
            "high": float(x[2]),
            "low": float(x[3]),
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
    gains = []
    losses = []
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
    tp1 = resistance
    risk = price - stop
    reward = tp1 - price
    rr = reward / risk if risk > 0 else 0.0
    return {
        "price": price,
        "ema20": e20,
        "ema50": e50,
        "rsi": rv,
        "support": support,
        "resistance": resistance,
        "entry_low": entry_low,
        "entry_high": entry_high,
        "stop": stop,
        "target": tp1,
        "rr": rr,
    }


def quality(ind):
    score = 0.0
    if ind["ema20"] > ind["ema50"]:
        score += 25
    if ind["price"] <= ind["support"] * 1.01:
        score += 20
    if ind["rsi"] < 65:
        score += 15
    if ind["rr"] >= 1:
        score += 20
    if ind["price"] >= ind["entry_low"] and ind["price"] <= ind["entry_high"]:
        score += 20
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
    """Score-based reversal model. It does not require bullish regime if reversal evidence is strong."""
    score = 0
    reasons = []
    if ind["rsi"] <= 30:
        score += 20; reasons.append("RSI oversold")
    elif ind["rsi"] <= 35:
        score += 12; reasons.append("RSI weak/oversold")
    if ind["price"] <= ind["support"] * 1.01:
        score += 20; reasons.append("near support")
    if ind["entry_low"] <= ind["price"] <= ind["entry_high"]:
        score += 20; reasons.append("entry zone")
    if ind["ema20"] > ind["ema50"]:
        score += 15; reasons.append("bullish EMA")
    else:
        # Reversal confirmation: current EMA gap is improving versus prior bar.
        prev = indicators(history[:-1])
        if prev and ind["ema20"] > prev["ema20"] and ind["ema50"] >= prev["ema50"]:
            score += 12; reasons.append("EMA recovery")
    closes = [x["close"] for x in history]
    if len(closes) >= 6 and closes[-1] > closes[-2] > closes[-3]:
        score += 15; reasons.append("price momentum recovery")
    if ind["rr"] >= 2:
        score += 10; reasons.append("strong R/R")
    elif ind["rr"] >= 1:
        score += 5; reasons.append("acceptable R/R")
    q = quality(ind)
    hard = q >= MIN_QUALITY and ind["rr"] >= MIN_RR
    confirmation = score >= 70
    return hard and confirmation, q, score, reasons


def simulate(candles, coin, strategy_name, signal_func):
    trades = []
    i = 50
    while i < len(candles) - 2:
        history = candles[:i + 1]
        ind = indicators(history)
        if not ind:
            i += 1
            continue
        result = signal_func(ind, history) if strategy_name == "SCORE" else signal_func(ind)
        buy = result[0]
        if not buy:
            i += 1
            continue
        # Conservative execution: next candle open, including slippage.
        entry_bar = candles[i + 1]
        entry = entry_bar["open"] * (1 + SLIPPAGE_RATE)
        stop = ind["stop"]
        target = ind["target"]
        risk = entry - stop
        if risk <= 0 or target <= entry:
            i += 1
            continue
        exit_price = None
        exit_time = None
        reason = "TIME"
        exit_index = min(i + 1 + MAX_HOLD_BARS, len(candles) - 1)
        for j in range(i + 1, exit_index + 1):
            bar = candles[j]
            # If both SL and TP occur in the same candle, assume SL first.
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
            coin=coin,
            strategy=strategy_name,
            entry_time=entry_bar["time"],
            exit_time=exit_time,
            entry=entry,
            exit=exit_price,
            stop=stop,
            target=target,
            r_multiple=r,
            pnl_pct=net * 100,
            bars=exit_index - (i + 1),
            reason=reason,
        ))
        i = exit_index + 1
    return trades


def metrics(trades):
    if not trades:
        return {
            "trades": 0, "win_rate_pct": 0, "profit_factor": 0,
            "expectancy_pct": 0, "average_r": 0, "max_drawdown_pct": 0,
            "net_return_pct": 0,
        }
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
        dd = (peak - equity) / peak * 100
        max_dd = max(max_dd, dd)
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
    print("\n=== CRYPTO ALERT BACKTEST ===")
    print(f"Period: approximately {months} months | Timeframe: 1H")
    print(f"Fees: {FEE_RATE*100:.2f}% per side | Slippage: {SLIPPAGE_RATE*100:.2f}% per side")
    for coin, by_strategy in results.items():
        print(f"\n--- {coin} ---")
        for name, data in by_strategy.items():
            m = data["metrics"]
            print(
                f"{name:>8}: trades={m['trades']:<4} "
                f"win={m['win_rate_pct']:>6}% "
                f"PF={m['profit_factor']} "
                f"expectancy={m['expectancy_pct']}% "
                f"avgR={m['average_r']} "
                f"DD={m['max_drawdown_pct']}% "
                f"return={m['net_return_pct']}%"
            )
    print("\nInterpretation: do NOT deploy a strategy from one metric alone. Require enough trades, PF > 1 after costs, acceptable drawdown, and stability across coins/regimes.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--months", type=int, default=12)
    parser.add_argument("--coins", nargs="+", default=DEFAULT_COINS)
    args = parser.parse_args()
    results = {}
    for coin in args.coins:
        coin = coin.upper()
        print(f"Downloading {coin} {args.months} months of 1H data...")
        try:
            candles = fetch_klines(coin, args.months)
            if len(candles) < 100:
                print(f"{coin}: insufficient candles ({len(candles)})")
                continue
            a = simulate(candles, coin, "CURRENT", current_strategy)
            b = simulate(candles, coin, "SCORE", score_strategy)
            results[coin] = {
                "CURRENT": {"metrics": metrics(a), "trades": a},
                "SCORE": {"metrics": metrics(b), "trades": b},
            }
            print(f"{coin}: {len(candles)} candles loaded")
        except Exception as exc:
            print(f"{coin}: ERROR: {exc}")
    print_report(results, args.months)


if __name__ == "__main__":
    main()
