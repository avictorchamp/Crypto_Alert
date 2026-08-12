"""
Crypto Alert Backtest Engine v2.0.0

READ-ONLY research tool. No Binance account access. No trading.

Purpose:
  1) Reproduce the current production-style entry logic as closely as practical.
  2) Test a stricter V2 idea: bullish regime + pullback/support + RSI recovery +
     price confirmation + minimum R/R.
  3) Use fixed-risk position sizing so one bad sequence cannot mathematically
     compound the portfolio to -100% simply because many signals overlap.
  4) Permit only ONE open position per coin and a maximum number of concurrent
     positions for the portfolio-level report.

Historical data: Coinbase Exchange public 1H candles.
Costs: fee and slippage on both entry and exit.

Usage:
    python backtest.py --months 12
    python backtest.py --months 24
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
RISK_PER_TRADE = 0.01
MAX_CONCURRENT_POSITIONS = 3
MAX_HOLD_BARS = 72
MIN_CURRENT_QUALITY = 70.0
MIN_V2_QUALITY = 70.0
MIN_RR = 1.5
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
    equity_pnl_pct: float
    bars: int
    reason: str


def utc_from_ms(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def fetch_klines(coin, months):
    product = f"{coin}-USD"
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=months * 30.4375)
    cursor = start
    rows = []
    session = requests.Session()
    session.headers.update({"User-Agent": "Crypto-Alert-Backtest/2.0"})

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
            cursor = max(chunk_end, datetime.fromtimestamp(max_ts + GRANULARITY, tz=timezone.utc))
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
    if len(history) < 50:
        return None
    closes = [x["close"] for x in history]
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


def current_signal(history):
    ind = indicators(history)
    if not ind:
        return False, ind, 0.0, "NO_DATA"
    q = quality(ind)
    in_entry = ind["entry_low"] <= ind["price"] <= ind["entry_high"]
    buy = (
        ind["ema20"] > ind["ema50"]
        and ind["price"] <= ind["support"] * 1.01
        and ind["rsi"] < 65
        and ind["rr"] >= 1.0
        and q >= MIN_CURRENT_QUALITY
        and in_entry
    )
    return buy, ind, q, "CURRENT"


def v2_signal(history):
    """Stricter, testable confirmation model.

    Hard filters:
      - bullish EMA20 > EMA50
      - price at/near support and inside the entry zone
      - R/R >= 1.5
      - quality >= 70

    Confirmation:
      - RSI was <= 35 on the previous candle and is recovering, OR
        price has two consecutive rising closes while RSI is recovering
      - current close > previous close
      - current close >= EMA20 is NOT required; pullbacks below EMA20 are allowed
        while EMA20 remains above EMA50.
    """
    if len(history) < 51:
        return False, None, 0.0, "NO_DATA"
    ind = indicators(history)
    prev = indicators(history[:-1])
    prev2 = indicators(history[:-2])
    if not ind or not prev or not prev2:
        return False, ind, 0.0, "NO_DATA"

    q = quality(ind)
    closes = [x["close"] for x in history]
    bullish_regime = ind["ema20"] > ind["ema50"]
    near_support = ind["price"] <= ind["support"] * 1.01
    in_entry = ind["entry_low"] <= ind["price"] <= ind["entry_high"]
    rr_ok = ind["rr"] >= MIN_RR
    price_confirmation = ind["price"] > prev["price"]
    rsi_recovery = ind["rsi"] > prev["rsi"] and (prev["rsi"] <= 35 or prev2["rsi"] <= 35)
    two_up = closes[-1] > closes[-2] > closes[-3] and ind["rsi"] > prev["rsi"]
    confirmation = price_confirmation and (rsi_recovery or two_up)

    buy = (
        bullish_regime and near_support and in_entry and rr_ok
        and q >= MIN_V2_QUALITY and confirmation
    )
    return buy, ind, q, "V2"


def build_trade(candles, i, coin, strategy_name, ind):
    entry_bar = candles[i + 1]
    entry = entry_bar["open"] * (1 + SLIPPAGE_RATE)
    stop = ind["stop"]
    target = ind["target"]
    risk = entry - stop
    if risk <= 0 or target <= entry:
        return None
    exit_index = min(i + 1 + MAX_HOLD_BARS, len(candles) - 1)
    exit_price = None
    reason = "TIME"
    for j in range(i + 1, exit_index + 1):
        bar = candles[j]
        # Conservative ordering when both levels are touched in one candle:
        # assume SL happened first.
        if bar["low"] <= stop:
            exit_price = stop * (1 - SLIPPAGE_RATE)
            exit_index = j
            reason = "SL"
            break
        if bar["high"] >= target:
            exit_price = target * (1 - SLIPPAGE_RATE)
            exit_index = j
            reason = "TP"
            break
    if exit_price is None:
        exit_price = candles[exit_index]["close"] * (1 - SLIPPAGE_RATE)
    gross = (exit_price - entry) / entry
    net = gross - 2 * FEE_RATE
    r = (exit_price - entry) / risk
    return Trade(
        coin=coin,
        strategy=strategy_name,
        entry_time=entry_bar["time"],
        exit_time=candles[exit_index]["time"],
        entry=entry,
        exit=exit_price,
        stop=stop,
        target=target,
        r_multiple=r,
        pnl_pct=net * 100,
        equity_pnl_pct=0.0,
        bars=exit_index - (i + 1),
        reason=reason,
    ), exit_index


def simulate_coin(candles, coin, strategy_name):
    trades = []
    i = 50
    while i < len(candles) - 2:
        history = candles[:i + 1]
        if strategy_name == "CURRENT":
            signal, ind, _, _ = current_signal(history)
        else:
            signal, ind, _, _ = v2_signal(history)
        if not signal:
            i += 1
            continue
        built = build_trade(candles, i, coin, strategy_name, ind)
        if not built:
            i += 1
            continue
        trade, exit_index = built
        trades.append(trade)
        # No overlapping position in the same coin.
        i = exit_index + 1
    return trades


def metrics(trades):
    if not trades:
        return {"trades": 0, "win_rate_pct": 0.0, "profit_factor": 0.0,
                "expectancy_pct": 0.0, "average_r": 0.0, "max_drawdown_pct": 0.0,
                "net_return_pct": 0.0}
    wins = [t for t in trades if t.pnl_pct > 0]
    losses = [t for t in trades if t.pnl_pct <= 0]
    gross_win = sum(t.pnl_pct for t in wins)
    gross_loss = abs(sum(t.pnl_pct for t in losses))
    pf = gross_win / gross_loss if gross_loss else float("inf")
    equity = INITIAL_EQUITY
    peak = equity
    max_dd = 0.0
    for t in trades:
        equity *= 1 + (RISK_PER_TRADE * t.r_multiple)
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


def portfolio_metrics(all_trades):
    """Portfolio-level event simulation with max 3 concurrent positions.

    Signals are generated independently for each coin. Trades are processed in
    chronological order. If 3 positions are already open at an entry time, the
    new signal is skipped. This is a conservative capacity constraint.
    """
    events = sorted(all_trades, key=lambda t: (t.entry_time, t.coin))
    active = []
    selected = []
    for t in events:
        active = [x for x in active if x.exit_time > t.entry_time]
        if len(active) < MAX_CONCURRENT_POSITIONS:
            active.append(t)
            selected.append(t)
    return metrics(selected), selected


def print_report(results, months):
    print("\n=== CRYPTO ALERT BACKTEST v2.0.0 ===")
    print(f"Period: approximately {months} months | Timeframe: 1H")
    print("Data: Coinbase Exchange public candles (USD pairs)")
    print(f"Fees: {FEE_RATE*100:.2f}% per side | Slippage: {SLIPPAGE_RATE*100:.2f}% per side")
    print(f"Risk/trade: {RISK_PER_TRADE*100:.1f}% | Max concurrent positions: {MAX_CONCURRENT_POSITIONS}")

    aggregate = {"CURRENT": [], "V2": []}
    for coin, by_strategy in results.items():
        print(f"\n--- {coin} ---")
        for name in ("CURRENT", "V2"):
            trades = by_strategy[name]
            aggregate[name].extend(trades)
            print(f"{name:>8}: {metrics(trades)}")

    print("\n=== TRADE-POOL COMPARISON ===")
    for name in ("CURRENT", "V2"):
        print(f"{name:>8}: {metrics(aggregate[name])}")

    print("\n=== PORTFOLIO CAPACITY COMPARISON ===")
    for name in ("CURRENT", "V2"):
        pm, selected = portfolio_metrics(aggregate[name])
        print(f"{name:>8}: {pm} | selected_trades={len(selected)}")

    print("\nDecision rule: do NOT deploy unless PF > 1 after costs, expectancy > 0, drawdown is acceptable, and performance is stable across coins/regimes.")


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
            current = simulate_coin(candles, coin, "CURRENT")
            v2 = simulate_coin(candles, coin, "V2")
            results[coin] = {"CURRENT": current, "V2": v2}
            print(f"{coin}: {len(candles)} candles loaded ({utc_from_ms(candles[0]['time']).date()} to {utc_from_ms(candles[-1]['time']).date()})")
        except Exception as exc:
            print(f"{coin}: ERROR: {exc}")

    print_report(results, args.months)


if __name__ == "__main__":
    main()
