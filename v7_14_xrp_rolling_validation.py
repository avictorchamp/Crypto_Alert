#!/usr/bin/env python3
"""V7.14 XRP rolling validation. Research/shadow only; production is unchanged."""
from __future__ import annotations
import json
from datetime import datetime,timedelta,timezone
from v7_6_coin_fingerprint import fetch,D,collect,learn_patterns
from v7_13_shadow_signal_simulation import freeze_rules,cond_match

SYMBOL="XRPUSDT"; WINDOW_DAYS=30; WINDOWS=3
MIN_SIGNALS_PER_WINDOW=5; MIN_PASS_WINDOWS=2
MIN_RATE=.50; MIN_AVG_CLOSE=0.0

def eval_rule(rows, rule, edges):
    m=[r for r in rows if cond_match(r,rule["label"],edges)]
    if not m: return {"signals":0,"directional_rate":None,"directional_avg_close":None,"passed":False}
    h=str(rule["horizon"]); closes=[r["outcomes"][h]["close"] for r in m]
    if rule["direction"]=="LONG":
        rate=sum(r["outcomes"][h]["max"]>=.02 for r in m)/len(m); avg=sum(closes)/len(closes)
    else:
        rate=sum(r["outcomes"][h]["min"]<=-.02 for r in m)/len(m); avg=-sum(closes)/len(closes)
    return {"signals":len(m),"directional_rate":rate,"directional_avg_close":avg,
            "passed":len(m)>=MIN_SIGNALS_PER_WINDOW and rate>=MIN_RATE and avg>=MIN_AVG_CLOSE}

def main():
    end=datetime.now(timezone.utc); forward_days=WINDOW_DAYS*WINDOWS
    start=end-timedelta(days=30.44*18+forward_days+5); freeze=end-timedelta(days=forward_days)
    btc=fetch(D,"BTCUSDT",start,end)
    hist=collect(SYMBOL,start,freeze,btc); rules=freeze_rules(hist)
    n=len(hist); learned=learn_patterns(hist[:int(n*.20)]); edges=learned["edges"]
    out_rules=[]
    for rule in rules:
        ws=[]
        for k in range(WINDOWS):
            a=freeze+timedelta(days=k*WINDOW_DAYS); b=a+timedelta(days=WINDOW_DAYS)
            rows=collect(SYMBOL,a,b,btc)
            z=eval_rule(rows,rule,edges); z.update({"window":k+1,"start":a.isoformat(),"end":b.isoformat()}); ws.append(z)
        pass_n=sum(x["passed"] for x in ws); observed=sum(x["signals"] for x in ws)
        out_rules.append({"direction":rule["direction"],"horizon_hours":rule["horizon"],"pattern":rule["label"],
                          "windows":ws,"pass_windows":pass_n,"total_signals":observed,
                          "rolling_gate_passed":pass_n>=MIN_PASS_WINDOWS and observed>=20})
    out={"version":"7.14.0-xrp-rolling-validation","production_changed":False,"mode":"SHADOW",
         "integration_status":"NOT_LIVE","symbol":SYMBOL,"window_days":WINDOW_DAYS,"windows":WINDOWS,
         "criteria":{"min_signals_per_window":MIN_SIGNALS_PER_WINDOW,"min_pass_windows":MIN_PASS_WINDOWS,
                     "min_directional_rate":MIN_RATE,"min_directional_avg_close":MIN_AVG_CLOSE,"min_total_signals":20},
         "rules":out_rules,"qualified_rules":sum(r["rolling_gate_passed"] for r in out_rules)}
    open("v7_14_xrp_rolling_results.json","w").write(json.dumps(out,indent=2))
    print(json.dumps(out,indent=2)); print("V7.14 XRP ROLLING VALIDATION COMPLETED"); print("PRODUCTION_CHANGED=False")
if __name__=="__main__": main()
