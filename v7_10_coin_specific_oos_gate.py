#!/usr/bin/env python3
"""V7.10 Coin-Specific Out-of-Sample Gate.

Research only. Patterns are learned from chronological training data, filtered on
validation, then evaluated once on a fully unseen test period. Production is never changed.
"""
from __future__ import annotations
import json
from datetime import datetime, timedelta, timezone
from v7_6_coin_fingerprint import (
    TARGETS, HORIZONS, collect, learn_patterns, apply_patterns, summarize, fetch, D
)

MIN_VALID=30
MIN_TEST=30
MIN_TRAIN=40
MIN_RATE_LIFT=0.03
MIN_CLOSE_EDGE=0.002

def direction(p, base):
    up_lift=p["up_rate"]-base["up_rate"]
    down_lift=p["down_rate"]-base["down_rate"]
    if up_lift >= MIN_RATE_LIFT and up_lift > down_lift:
        return "LONG"
    if down_lift >= MIN_RATE_LIFT and down_lift > up_lift:
        return "SHORT"
    return None

def evaluate_patterns(rows, learned):
    # Re-evaluate every learned pattern, not just the top 10, to avoid a
    # ranking artifact becoming the OOS gate.
    edges=learned["edges"]
    results=[]
    for p in learned["patterns"]:
        label=p["label"]; h=str(p["horizon"])
        conditions=[label] if isinstance(label,(list,tuple)) and len(label)==2 and isinstance(label[0],str) else list(label)
        matched=[]
        for r in rows:
            ok=True
            for f,v in conditions:
                if f in ("h1_trend","d1_trend","btc_regime"):
                    ok = ok and str(r["features"][f])==str(v)
                else:
                    ok = ok and bucket_value(r["features"][f], edges[f])==int(v)
            if ok: matched.append(r)
        if len(matched) < 1: continue
        results.append({
            "label":label, "horizon":p["horizon"], "n":len(matched),
            "up_rate":sum(r["outcomes"][h]["max"]>=.02 for r in matched)/len(matched),
            "down_rate":sum(r["outcomes"][h]["min"]<=-.02 for r in matched)/len(matched),
            "avg_close":sum(r["outcomes"][h]["close"] for r in matched)/len(matched)
        })
    return results

def bucket_value(x, edges):
    for i in range(len(edges)-1):
        if edges[i] <= x <= edges[i+1]:
            return i
    return len(edges)-2

def gate_coin(rows):
    n=len(rows); a=int(n*.20); b=int(n*.60)
    train, valid, test=rows[:a], rows[a:b], rows[b:]
    learned=learn_patterns(train)
    vp=evaluate_patterns(valid, learned)
    tp=evaluate_patterns(test, learned)
    bykey={(str(x["label"]),x["horizon"]):x for x in vp}
    candidates=[]
    for p in tp:
        if p["n"] < MIN_TEST: continue
        key=(str(p["label"]),p["horizon"])
        v=bykey.get(key)
        if not v or v["n"] < MIN_VALID: continue
        tr=next((x for x in learned["patterns"] if str(x["label"])==str(p["label"]) and x["horizon"]==p["horizon"]),None)
        if not tr or tr["n"] < MIN_TRAIN: continue
        base_v=next((x for x in summarize(valid).values() if False),None)
        h=str(p["horizon"])
        bv=summarize(valid)[h]; bt=summarize(test)[h]; btr=summarize(train)[h]
        d=direction(tr,btr)
        if not d: continue
        if d=="LONG":
            valid_ok=(v["up_rate"]-bv["up_rate"]>=MIN_RATE_LIFT and v["avg_close"]-bv["avg_close"]>=MIN_CLOSE_EDGE)
            test_ok=(p["up_rate"]-bt["up_rate"]>=MIN_RATE_LIFT and p["avg_close"]-bt["avg_close"]>=MIN_CLOSE_EDGE)
        else:
            valid_ok=(v["down_rate"]-bv["down_rate"]>=MIN_RATE_LIFT and v["avg_close"]-bv["avg_close"]<=-MIN_CLOSE_EDGE)
            test_ok=(p["down_rate"]-bt["down_rate"]>=MIN_RATE_LIFT and p["avg_close"]-bt["avg_close"]<=-MIN_CLOSE_EDGE)
        if valid_ok and test_ok:
            candidates.append({
                "label":p["label"],"horizon":p["horizon"],"direction":d,
                "train_n":tr["n"],"validation_n":v["n"],"test_n":p["n"],
                "train_edge_rate":(tr["up_rate"]-btr["up_rate"]) if d=="LONG" else (tr["down_rate"]-btr["down_rate"]),
                "validation_edge_rate":(v["up_rate"]-bv["up_rate"]) if d=="LONG" else (v["down_rate"]-bv["down_rate"]),
                "test_edge_rate":(p["up_rate"]-bt["up_rate"]) if d=="LONG" else (p["down_rate"]-bt["down_rate"]),
                "train_avg_close":tr["avg_close"],"validation_avg_close":v["avg_close"],
                "test_avg_close":p["avg_close"],"baseline_test_avg_close":bt["avg_close"]
            })
    candidates.sort(key=lambda x:(x["test_edge_rate"],x["test_avg_close"] if x["direction"]=="LONG" else -x["test_avg_close"]), reverse=True)
    return {
        "events":n,
        "split":{"train":len(train),"validation":len(valid),"unseen_test":len(test)},
        "baseline":{"train":summarize(train),"validation":summarize(valid),"unseen_test":summarize(test)},
        "top_training_patterns":learned["patterns"][:10],
        "validation_pattern_count":len(vp),
        "unseen_test_pattern_count":len(tp),
        "oos_candidates":candidates[:20],
        "gate_passed":len(candidates)>0
    }

def main():
    end=datetime.now(timezone.utc); start=end-timedelta(days=30.44*18)
    btc_d=fetch(D,"BTCUSDT",start,end)
    results={}
    for s in TARGETS:
        rows=collect(s,start,end,btc_d)
        results[s]=gate_coin(rows)
    total=sum(len(x["oos_candidates"]) for x in results.values())
    passed=[s for s,x in results.items() if x["gate_passed"]]
    out={
      "version":"7.10.0-coin-specific-oos-gate",
      "production_changed":False,
      "purpose":"Verify whether V7.6 per-coin patterns retain directional edge on validation and unseen chronological test data",
      "targets":TARGETS,"horizons_hours":list(HORIZONS),"period_months":18,
      "thresholds":{"min_train_support":MIN_TRAIN,"min_validation_support":MIN_VALID,"min_test_support":MIN_TEST,
                   "min_directional_rate_lift":MIN_RATE_LIFT,"min_avg_close_edge":MIN_CLOSE_EDGE},
      "gate_rule":"A candidate must have the same directional edge on validation and unseen test, with minimum support and minimum rate/close-return edge on both periods.",
      "coins_with_oos_candidates":passed,"total_oos_candidates":total,"results":results
    }
    with open("v7_10_coin_specific_oos_gate_results.json","w") as f: json.dump(out,f,indent=2)
    print(json.dumps(out,indent=2))
    print("V7.10 RESEARCH GATE COMPLETED")
    print("PRODUCTION_CHANGED=False")
if __name__=="__main__": main()
