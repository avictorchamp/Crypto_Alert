#!/usr/bin/env python3
"""V7.4 locked-rule final confirmation for BTC/ETH/SOL/XRP.

Exact same methodology as the BNB V7.4 final confirmation:
- 30 months of data
- last 18 months evaluated in six chronological ~3-month windows
- 1D_BULL_FILTER + locked momentum rule
- no per-coin rule optimization
Research only; production is untouched.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from backtest_coin_specific import (
    D, FEE, H, HORIZON, SLIP, SYMBOLS,
    daily_regime, feat, fetch, outcome, rules, stats,
)

TARGETS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]
MODE = "1D_BULL_FILTER"
LOCKED_RULE = "momentum"


def confirm_symbol(symbol: str, end: datetime):
    start = end - timedelta(days=30.44 * 30)
    h = fetch(H, symbol, start, end)
    d = fetch(D, symbol, start, end)

    if len(h) < 1000 or len(d) < 50:
        raise RuntimeError(
            f"{symbol}: insufficient data 1h={len(h)} 1d={len(d)}"
        )

    events = []
    for i in range(51, len(h) - HORIZON):
        o = outcome(h, i)
        if o is not None:
            events.append(
                (
                    h[i]["t"],
                    daily_regime(d, h[i]["t"]),
                    o,
                    rules(feat(h, i)),
                )
            )

    cutoff = int(
        (end - timedelta(days=18 * 30.44)).timestamp() * 1000
    )
    oos = [e for e in events if e[0] >= cutoff]
    if not oos:
        raise RuntimeError(f"{symbol}: no OOS events")

    lo = min(e[0] for e in oos)
    hi = max(e[0] for e in oos)
    span = max(1, hi - lo + 1)

    windows = []
    for w in range(6):
        a = lo + (span * w) // 6
        b = lo + (span * (w + 1)) // 6 if w < 5 else hi + 1
        windows.append([e for e in oos if a <= e[0] < b])

    folds = []
    all_rows = []
    for idx, win in enumerate(windows, 1):
        rows = [
            e[2]
            for e in win
            if e[1] == "BULL" and e[3].get(LOCKED_RULE)
        ]
        all_rows.extend(rows)
        st = stats(rows)
        folds.append(
            {
                "window": idx,
                "start_utc": (
                    datetime.fromtimestamp(
                        win[0][0] / 1000, timezone.utc
                    ).date().isoformat()
                    if win else None
                ),
                "end_utc": (
                    datetime.fromtimestamp(
                        win[-1][0] / 1000, timezone.utc
                    ).date().isoformat()
                    if win else None
                ),
                "stats": st,
                "positive": bool(
                    st["trades"]
                    and (st["expectancy_pct"] or 0) > 0
                    and (st["profit_factor"] or 0) > 1.0
                ),
            }
        )

    combined = stats(all_rows)
    positive = sum(x["positive"] for x in folds)
    pass_gate = bool(
        positive >= 4
        and combined["trades"] >= 75
        and (combined["profit_factor"] or 0) > 1.05
        and (combined["expectancy_pct"] or -999) > 0
    )

    return {
        "version": "7.4.0",
        "symbol": symbol,
        "mode": MODE,
        "locked_rule": LOCKED_RULE,
        "rules_reoptimized": False,
        "data_window_months": 30,
        "confirmation_window": "last_18_months",
        "folds": 6,
        "fold_length": "~3_months",
        "entry_interval": "1h",
        "context_interval": "1d",
        "horizon_hours": HORIZON,
        "costs": {"fee_per_side": FEE, "slippage_per_side": SLIP},
        "gate": ">=4/6 positive windows, >=75 combined trades, PF>1.05, positive expectancy",
        "production_changed": False,
        "candles_1h": len(h),
        "candles_1d": len(d),
        "events": len(events),
        "windows": folds,
        "combined_last_18m": combined,
        "positive_windows": positive,
        "confirmation_pass": pass_gate,
    }


def main():
    end = datetime.now(timezone.utc)
    results = {}
    for symbol in TARGETS:
        try:
            results[symbol] = confirm_symbol(symbol, end)
        except Exception as exc:
            results[symbol] = {
                "symbol": symbol,
                "confirmation_pass": False,
                "error": str(exc),
                "production_changed": False,
            }

    out = {
        "version": "7.4.0",
        "purpose": "MULTI_COIN_LOCKED_RULE_FINAL_CONFIRMATION",
        "rule_source": "V7.2_TRUE_OOS_SELECTION",
        "rules_reoptimized": False,
        "symbols": TARGETS,
        "mode": MODE,
        "locked_rule": LOCKED_RULE,
        "production_changed": False,
        "results": results,
    }
    with open("backtest_v7_4_multi_confirmation_results.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
