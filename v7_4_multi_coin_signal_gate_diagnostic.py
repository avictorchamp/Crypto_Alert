#!/usr/bin/env python3
"""V7.4 research-only signal gate diagnostic. No production changes."""
from __future__ import annotations
import json
from datetime import datetime,timedelta,timezone
from backtest_coin_specific import D,H,HORIZON,daily_regime,feat,fetch,rules

TARGETS=["BTCUSDT","ETHUSDT","SOLUSDT","XRPUSDT"]

def diagnose(symbol,end):
    start=end-timedelta(days=30.44*30)
    h=fetch(H,symbol,start,end); d=fetch(D,symbol,start,end)
    cutoff=int((end-timedelta(days=18*30.44)).timestamp()*1000)
    events=[]
    for i in range(51,len(h)-HORIZON):
        o=__import__("backtest_coin_specific").outcome(h,i)
        if o is not None and h[i]["t"]>=cutoff:
            x=feat(h,i); p,e20,e50,r,sup,res,avg,vol,va=x
            rr=(res-((sup+sup*1.005)/2))/((((sup+sup*1.005)/2)-sup*.99)) if sup>0 else 0
            bull=e20>e50
            momentum_price=p>avg*1.01
            volume=vol>=1.5*va
            rr_ok=rr>=1
            momentum=rules(x)["momentum"]
            events.append({"bull":bull,"momentum_price":momentum_price,"volume":volume,"rr":rr_ok,"momentum":momentum,"regime":daily_regime(d,h[i]["t"])})
    n=len(events)
    def count(pred): return sum(1 for e in events if pred(e))
    bull=count(lambda e:e["regime"]=="BULL")
    bull_momentum=count(lambda e:e["regime"]=="BULL" and e["momentum_price"] and e["volume"] and e["rr"])
    full=count(lambda e:e["regime"]=="BULL" and e["momentum"])
    return {"symbol":symbol,"events_oos":n,
      "gates":{"1D_BULL":bull,
               "1D_BULL_pct":round(100*bull/n,2) if n else None,
               "MOMENTUM_PRICE_after_BULL":count(lambda e:e["regime"]=="BULL" and e["momentum_price"]),
               "VOLUME_after_BULL_PRICE":count(lambda e:e["regime"]=="BULL" and e["momentum_price"] and e["volume"]),
               "RR_after_BULL_PRICE_VOLUME":bull_momentum,
               "FULL_LOCKED_MOMENTUM":full},
      "checks":{"bull_1h_ema":count(lambda e:e["bull"]),
                "momentum_price":count(lambda e:e["momentum_price"]),
                "volume_1_5x":count(lambda e:e["volume"]),
                "rr_ge_1":count(lambda e:e["rr"]),
                "locked_momentum_rule":count(lambda e:e["momentum"])}}

def main():
    end=datetime.now(timezone.utc); out={"version":"7.4.0-gate-diagnostic","production_changed":False,"results":{}}
    for s in TARGETS:
        try: out["results"][s]=diagnose(s,end)
        except Exception as e: out["results"][s]={"symbol":s,"error":str(e),"production_changed":False}
    with open("v7_4_multi_coin_signal_gate_diagnostic_results.json","w") as f: json.dump(out,f,indent=2)
    print(json.dumps(out,indent=2))
if __name__=="__main__": main()
