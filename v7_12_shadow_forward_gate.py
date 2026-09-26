#!/usr/bin/env python3
"""V7.12 Shadow Forward Gate: freeze V7.11 rules, evaluate a later forward slice."""
from __future__ import annotations
import json, math
from datetime import datetime,timedelta,timezone
from v7_6_coin_fingerprint import TARGETS,fetch,D,collect,learn_patterns
from v7_11_coin_specific_strategy_builder import build_rules

FORWARD_DAYS=45
MIN_SIGNALS=20
MIN_DIRECTIONAL_RATE=0.50
MIN_AVG_CLOSE=0.0

def cond_match(r,label,edges):
    cond=[label] if isinstance(label,(list,tuple)) and len(label)==2 and isinstance(label[0],str) else list(label)
    for f,v in cond:
        if f in ("h1_trend","d1_trend","btc_regime"):
            if str(r["features"][f])!=str(v): return False
        else:
            x=r["features"][f]; e=edges[f]
            b=next((i for i in range(len(e)-1) if e[i]<=x<=e[i+1]),len(e)-2)
            if b!=int(v): return False
    return True

def main():
    end=datetime.now(timezone.utc)
    all_start=end-timedelta(days=30.44*18+FORWARD_DAYS+5)
    train_end=end-timedelta(days=FORWARD_DAYS)
    btc=fetch(D,"BTCUSDT",all_start,end)
    frozen={}
    for s in TARGETS:
        rows=collect(s,all_start,train_end,btc)
        n=len(rows); a=int(n*.20); b=int(n*.60)
        learned=learn_patterns(rows[:a])
        # Reproduce V7.11 frozen rules from the same historical boundary.
        # gate candidates are regenerated, then only the deterministic V7.11 rules are retained.
        from v7_10_coin_specific_oos_gate import gate_coin
        gated=gate_coin(rows)
        candidates=gated["oos_candidates"]
        candidates.sort(key=lambda c:(abs(c["test_edge_rate"])*math.log1p(c["test_n"])+abs(c["test_avg_close"]-c["baseline_test_avg_close"]),c["test_n"],c["test_edge_rate"]),reverse=True)
        frozen[s]=candidates[:2]
    forward={}
    for s in TARGETS:
        rows=collect(s,train_end,end,btc)
        # Build bucket edges from pre-forward data so the forward period remains unseen.
        hist=collect(s,all_start,train_end,btc)
        n=len(hist); a=int(n*.20)
        learned=learn_patterns(hist[:a])
        rules=frozen[s]
        obs=[]
        for rule in rules:
            matches=[r for r in rows if cond_match(r,rule["label"],learned["edges"])]
            h=str(rule["horizon"])
            if matches:
                close=[r["outcomes"][h]["close"] for r in matches]
                up=[r["outcomes"][h]["max"]>=.02 for r in matches]
                down=[r["outcomes"][h]["min"]<=-.02 for r in matches]
                if rule["direction"]=="LONG":
                    rate=sum(up)/len(up); avg=sum(close)/len(close)
                else:
                    rate=sum(down)/len(down); avg=-sum(close)/len(close)
                obs.append({"direction":rule["direction"],"horizon_hours":rule["horizon"],"pattern":rule["label"],
                            "signals":len(matches),"directional_rate":rate,"directional_avg_close":avg})
        forward[s]={"forward_events":len(rows),"rules_observed":obs}
    allobs=[o for x in forward.values() for o in x["rules_observed"]]
    total=sum(o["signals"] for o in allobs)
    qualified=[o for o in allobs if o["signals"]>=MIN_SIGNALS and o["directional_rate"]>=MIN_DIRECTIONAL_RATE and o["directional_avg_close"]>=MIN_AVG_CLOSE]
    out={"version":"7.12.0-shadow-forward-gate","production_changed":False,"mode":"SHADOW",
         "integration_status":"NOT_LIVE","forward_days":FORWARD_DAYS,
         "rule_source":"V7.11 deterministic rules","total_forward_signal_observations":total,
         "qualified_observations":len(qualified),"results":forward,
         "gate_rule":"Forward observation is informational; no production integration unless sufficient new observations meet support, directional-rate, and average-close criteria.",
         "min_signals":MIN_SIGNALS,"min_directional_rate":MIN_DIRECTIONAL_RATE,"min_directional_avg_close":MIN_AVG_CLOSE}
    open("v7_12_shadow_forward_results.json","w").write(json.dumps(out,indent=2))
    print(json.dumps(out,indent=2)); print("V7.12 SHADOW FORWARD GATE COMPLETED"); print("PRODUCTION_CHANGED=False")
if __name__=="__main__": main()
