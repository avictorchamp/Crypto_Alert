#!/usr/bin/env python3
"""V7.4 research-only cross-coin gate robustness experiment.

Purpose:
- Test whether a gate choice selected on earlier data generalizes to later unseen data.
- Compare one shared gate across BTC/ETH/SOL/XRP with coin-specific gate selection.
- Never select using the holdout period.
- No production changes.
"""
from __future__ import annotations
import json
from datetime import datetime, timedelta, timezone
from backtest_coin_specific import H, D, HORIZON, feat, fetch, daily_regime, outcome

TARGETS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]
VARIANTS = (
    "baseline",
    "price_relaxed",
    "volume_relaxed",
    "price_only",
    "volume_only",
    "both_relaxed",
)

def gate(x, variant):
    p, e20, e50, r, sup, res, avg, vol, va = x
    mid = (sup + sup * 1.005) / 2
    rr = (res - mid) / (mid - sup * 0.99) if sup > 0 else 0
    return {
        "baseline": p > avg * 1.01 and vol >= 1.5 * va and rr >= 1,
        "price_relaxed": p > avg * 1.005 and vol >= 1.5 * va and rr >= 1,
        "volume_relaxed": p > avg * 1.01 and vol >= 1.2 * va and rr >= 1,
        "price_only": p > avg * 1.01 and rr >= 1,
        "volume_only": vol >= 1.5 * va and rr >= 1,
        "both_relaxed": p > avg * 1.005 and vol >= 1.2 * va and rr >= 1,
    }[variant]

def stats(rows):
    if not rows:
        return {"trades": 0, "win_rate_pct": None, "expectancy_pct": None, "profit_factor": None}
    r = [z[0] for z in rows]
    wins = [z for z in r if z > 0]
    loss = -sum(z for z in r if z < 0)
    pf = sum(wins) / loss if loss else None
    return {
        "trades": len(r),
        "win_rate_pct": round(100 * len(wins) / len(r), 2),
        "expectancy_pct": round(100 * sum(r) / len(r), 4),
        "profit_factor": round(pf, 3) if pf is not None else None,
    }

def collect(symbol, end):
    start = end - timedelta(days=30.44 * 18)
    h = fetch(H, symbol, start, end)
    d = fetch(D, symbol, start, end)
    events = []
    for i in range(51, len(h) - HORIZON):
        o = outcome(h, i)
        if o is None or daily_regime(d, h[i]["t"]) != "BULL":
            continue
        events.append((h[i]["t"], o, feat(h, i)))
    return events

def variant_stats(events, variant, lo, hi):
    rows = [events[i][1] for i in range(lo, hi) if gate(events[i][2], variant)]
    return stats(rows)

def select_variant(scores):
    # Selection uses training data only. Require meaningful trade count, then maximize
    # expectancy; PF is a tie-breaker. No holdout information enters this function.
    eligible = []
    for name, s in scores.items():
        if s["trades"] >= 40 and (s["expectancy_pct"] or -999) > 0 and (s["profit_factor"] or 0) > 1:
            eligible.append((s["expectancy_pct"], s["profit_factor"], name))
    if not eligible:
        return "baseline"
    eligible.sort(reverse=True)
    return eligible[0][2]

def main():
    end = datetime.now(timezone.utc)
    all_events = {}
    for symbol in TARGETS:
        try:
            all_events[symbol] = collect(symbol, end)
        except Exception as e:
            all_events[symbol] = {"error": str(e)}

    valid = {s: e for s, e in all_events.items() if not isinstance(e, dict)}
    errors = {s: e for s, e in all_events.items() if isinstance(e, dict)}
    if errors:
        raise RuntimeError(json.dumps(errors))

    # Temporal split: first 10% is warm-up, then 60% selection/training and final 30% holdout.
    # The holdout is never used to choose a variant.
    splits = {}
    train_scores = {}
    holdout_scores = {}
    for s, events in valid.items():
        n = len(events)
        warm = n // 10
        usable = n - warm
        train_end = warm + int(usable * 0.60)
        train_scores[s] = {v: variant_stats(events, v, warm, train_end) for v in VARIANTS}
        holdout_scores[s] = {v: variant_stats(events, v, train_end, n) for v in VARIANTS}
        splits[s] = {"events": n, "warmup_end": warm, "train_end": train_end, "holdout_start": train_end}

    shared_train = {}
    for v in VARIANTS:
        rows = []
        for s, events in valid.items():
            n = len(events); warm = splits[s]["warmup_end"]; train_end = splits[s]["train_end"]
            rows += [events[i][1] for i in range(warm, train_end) if gate(events[i][2], v)]
        shared_train[v] = stats(rows)

    shared_variant = select_variant(shared_train)
    coin_variants = {s: select_variant(train_scores[s]) for s in TARGETS}

    shared_holdout_rows = []
    coin_holdout_rows = {}
    for s, events in valid.items():
        start = splits[s]["holdout_start"]; n = len(events)
        shared_holdout_rows += [events[i][1] for i in range(start, n) if gate(events[i][2], shared_variant)]
        v = coin_variants[s]
        coin_holdout_rows[s] = [events[i][1] for i in range(start, n) if gate(events[i][2], v)]

    shared_holdout = stats(shared_holdout_rows)
    coin_holdout = {s: stats(rows) for s, rows in coin_holdout_rows.items()}
    baseline_holdout = {}
    for s, events in valid.items():
        start = splits[s]["holdout_start"]
        baseline_holdout[s] = variant_stats(events, "baseline", start, len(events))

    def holdout_pass(s):
        return s["trades"] >= 30 and (s["profit_factor"] or 0) > 1.05 and (s["expectancy_pct"] or -999) > 0

    out = {
        "version": "7.4.0-cross-coin-robustness",
        "production_changed": False,
        "period_months": 18,
        "targets": TARGETS,
        "selection_rule": "training only: trades>=40, expectancy>0, PF>1; maximize expectancy, PF tie-breaker; fallback baseline",
        "split_rule": "10% warmup, next 60% training/selection, final 30% unseen holdout",
        "holdout_rule": "trades>=30, PF>1.05, positive expectancy",
        "shared_variant": shared_variant,
        "coin_specific_variants": coin_variants,
        "shared_training": shared_train,
        "coin_training": train_scores,
        "splits": splits,
        "shared_holdout": shared_holdout,
        "shared_holdout_pass": holdout_pass(shared_holdout),
        "coin_specific_holdout": coin_holdout,
        "coin_specific_holdout_pass": {s: holdout_pass(v) for s, v in coin_holdout.items()},
        "baseline_holdout": baseline_holdout,
        "holdout_advantage_vs_baseline": {
            s: {
                "selected_variant": coin_variants[s],
                "expectancy_delta_pct_points": round((coin_holdout[s]["expectancy_pct"] or 0) - (baseline_holdout[s]["expectancy_pct"] or 0), 4),
                "pf_delta": round((coin_holdout[s]["profit_factor"] or 0) - (baseline_holdout[s]["profit_factor"] or 0), 3),
            } for s in TARGETS
        },
    }
    print(json.dumps(out, indent=2))
    with open("v7_4_cross_coin_robustness_results.json", "w") as f:
        json.dump(out, f, indent=2)

if __name__ == "__main__":
    main()
