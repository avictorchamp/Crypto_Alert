#!/usr/bin/env python3
"""V7.13 Shadow Signal Simulation: extend frozen V7.11 rules into a 90-day unseen forward slice."""
from __future__ import annotations
import json, math
from datetime import datetime, timedelta, timezone
from v7_6_coin_fingerprint import TARGETS, fetch, D, collect, learn_patterns
from v7_10_coin_specific_oos_gate import gate_coin

FORWARD_DAYS = 90

def cond_match(r, label, edges):
    cond = [label] if isinstance(label, (list, tuple)) and len(label) == 2 and isinstance(label[0], str) else list(label)
    for f, v in cond:
        if f in ("h1_trend", "d1_trend", "btc_regime"):
            if str(r["features"][f]) != str(v):
                return False
        else:
            x = r["features"][f]
            e = edges[f]
            b = next((i for i in range(len(e)-1) if e[i] <= x <= e[i+1]), len(e)-2)
            if b != int(v):
                return False
    return True

def freeze_rules(rows):
    gate = gate_coin(rows)
    candidates = gate["oos_candidates"]
    candidates.sort(
        key=lambda c: (
            abs(c["test_edge_rate"]) * math.log1p(c["test_n"])
            + abs(c["test_avg_close"] - c["baseline_test_avg_close"]),
            c["test_n"],
            c["test_edge_rate"],
        ),
        reverse=True,
    )
    return candidates[:2]

def main():
    end = datetime.now(timezone.utc)
    all_start = end - timedelta(days=30.44 * 18 + FORWARD_DAYS + 5)
    train_end = end - timedelta(days=FORWARD_DAYS)

    btc = fetch(D, "BTCUSDT", all_start, end)
    results = {}
    frozen_rules = {}

    for symbol in TARGETS:
        historical = collect(symbol, all_start, train_end, btc)
        forward = collect(symbol, train_end, end, btc)
        rules = freeze_rules(historical)
        frozen_rules[symbol] = rules

        hist_n = len(historical)
        train_n = int(hist_n * 0.20)
        learned = learn_patterns(historical[:train_n])

        observations = []
        for rule in rules:
            matches = [r for r in forward if cond_match(r, rule["label"], learned["edges"])]
            horizon = str(rule["horizon"])
            if not matches:
                continue
            closes = [r["outcomes"][horizon]["close"] for r in matches]
            ups = [r["outcomes"][horizon]["max"] >= 0.02 for r in matches]
            downs = [r["outcomes"][horizon]["min"] <= -0.02 for r in matches]
            if rule["direction"] == "LONG":
                rate = sum(ups) / len(ups)
                avg_close = sum(closes) / len(closes)
            else:
                rate = sum(downs) / len(downs)
                avg_close = -sum(closes) / len(closes)
            observations.append({
                "direction": rule["direction"],
                "horizon_hours": rule["horizon"],
                "pattern": rule["label"],
                "signals": len(matches),
                "directional_rate": rate,
                "directional_avg_close": avg_close,
            })

        results[symbol] = {
            "historical_events": len(historical),
            "forward_events": len(forward),
            "frozen_rules": len(rules),
            "rules_observed": observations,
        }

    all_obs = [o for x in results.values() for o in x["rules_observed"]]
    total_signals = sum(o["signals"] for o in all_obs)
    qualified_20 = [
        o for o in all_obs
        if o["signals"] >= 20 and o["directional_rate"] >= 0.50 and o["directional_avg_close"] >= 0
    ]
    qualified_10 = [
        o for o in all_obs
        if o["signals"] >= 10 and o["directional_rate"] >= 0.50 and o["directional_avg_close"] >= 0
    ]

    out = {
        "version": "7.13.0-shadow-signal-simulation",
        "production_changed": False,
        "mode": "SHADOW",
        "integration_status": "NOT_LIVE",
        "forward_days": FORWARD_DAYS,
        "rule_source": "V7.11 deterministic rules frozen before forward slice",
        "total_forward_signal_observations": total_signals,
        "observed_rule_count": len(all_obs),
        "qualified_20_signal_rules": len(qualified_20),
        "qualified_10_signal_rules": len(qualified_10),
        "results": results,
        "interpretation": "Simulation only. No production integration or live alert change."
    }
    with open("v7_13_shadow_signal_results.json", "w") as f:
        json.dump(out, f, indent=2)
    print(json.dumps(out, indent=2))
    print("V7.13 SHADOW SIGNAL SIMULATION COMPLETED")
    print("PRODUCTION_CHANGED=False")

if __name__ == "__main__":
    main()
