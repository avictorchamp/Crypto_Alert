#!/usr/bin/env python3
"""V7.11 Coin-Specific Strategy Builder — research/shadow only.

Consumes the V7.10 OOS gate deterministically, builds per-coin signal rules,
removes duplicate rules, and emits a shadow strategy artifact. Production is
never changed.
"""
from __future__ import annotations
import json, math
from datetime import datetime, timedelta, timezone
from v7_6_coin_fingerprint import TARGETS, HORIZONS, collect, fetch, D
from v7_10_coin_specific_oos_gate import gate_coin

MIN_TEST_SUPPORT = 30
MAX_RULES_PER_COIN = 2

def label_key(label):
    if isinstance(label, (list, tuple)):
        return tuple(tuple(x) if isinstance(x, (list, tuple)) else x for x in label)
    return label

def rule_score(c):
    # Deterministic ordering only; not a profitability forecast.
    edge = abs(float(c["test_edge_rate"]))
    close = abs(float(c["test_avg_close"] - c["baseline_test_avg_close"]))
    support = math.log1p(int(c["test_n"]))
    return edge * support + close

def build_rules(results):
    rules = {}
    for coin, data in results.items():
        candidates = data["oos_candidates"]
        seen = set()
        unique = []
        for c in candidates:
            key=(label_key(c["label"]), int(c["horizon"]), c["direction"])
            if key in seen:
                continue
            seen.add(key)
            unique.append(c)
        unique.sort(key=lambda c:(rule_score(c), c["test_n"], c["test_edge_rate"]), reverse=True)
        rules[coin] = []
        for c in unique[:MAX_RULES_PER_COIN]:
            rules[coin].append({
                "symbol": coin,
                "direction": c["direction"],
                "horizon_hours": c["horizon"],
                "pattern": c["label"],
                "train_support": c["train_n"],
                "validation_support": c["validation_n"],
                "unseen_test_support": c["test_n"],
                "validation_edge_rate": c["validation_edge_rate"],
                "unseen_test_edge_rate": c["test_edge_rate"],
                "validation_avg_close": c["validation_avg_close"],
                "unseen_test_avg_close": c["test_avg_close"],
                "unseen_test_baseline_avg_close": c["baseline_test_avg_close"],
                "selection_score": rule_score(c),
                "mode": "SHADOW"
            })
    return rules

def main():
    end=datetime.now(timezone.utc)
    start=end-timedelta(days=30.44*18)
    btc_d=fetch(D,"BTCUSDT",start,end)
    results={}
    for symbol in TARGETS:
        rows=collect(symbol,start,end,btc_d)
        results[symbol]=gate_coin(rows)
    rules=build_rules(results)
    total=sum(len(v) for v in rules.values())
    out={
      "version":"7.11.0-coin-specific-strategy-builder",
      "production_changed":False,
      "mode":"SHADOW",
      "purpose":"Convert V7.10 validation+unseen-test candidates into deterministic per-coin shadow signal rules without changing live production.",
      "source_gate":"7.10.0-coin-specific-oos-gate",
      "targets":TARGETS,
      "max_rules_per_coin":MAX_RULES_PER_COIN,
      "total_shadow_rules":total,
      "rules_by_coin":rules,
      "integration_status":"NOT_LIVE",
      "notes":[
        "Rules are research/shadow only.",
        "No live alert routing or production strategy file is modified.",
        "Selection is limited to candidates already passing V7.10; it does not claim future profitability.",
        "A later shadow-observation gate is required before any production integration."
      ]
    }
    with open("v7_11_coin_specific_strategy_results.json","w") as f:
        json.dump(out,f,indent=2)
    print(json.dumps(out,indent=2))
    print("V7.11 STRATEGY BUILDER COMPLETED")
    print("SHADOW_RULES:", total)
    print("PRODUCTION_CHANGED=False")

if __name__=="__main__":
    main()
