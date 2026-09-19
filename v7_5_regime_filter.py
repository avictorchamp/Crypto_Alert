#!/usr/bin/env python3
"""V7.5 research-only regime filter experiment.
Tests whether conditioning the existing Momentum/Volume entry on additional
trend/regime context improves chronological walk-forward robustness.
"""
from __future__ import annotations
import json
from datetime import datetime,timedelta,timezone
from backtest_coin_specific import H,D,HORIZON,feat,fetch,daily_regime,outcome,ema,stats

TARGETS=["BTCUSDT","ETHUSDT","SOLUSDT","XRPUSDT"]
VARIANTS=("baseline","h1_trend","strong_1d","trend_momentum","trend_volume","h1_reclaim")

def regime_features(h,d,i):
    p,e20,e50,r,sup,res,avg,vol,va=feat(h,i)
    rows=[x for x in d if x["t"]<=h[i]["t"]]
    c=[x["c"] for x in rows[-50:]] if len(rows)>=50 else []
    de20=ema(c[-20:],20) if len(c)>=20 else None
    de50=ema(c,50) if len(c)>=50 else None
    return {
        "h1_trend":p>e20,
        "strong_1d":de20 is not None and de50 is not None and de20>de50*1.005,
        "trend_momentum":p>e20 and p>avg*1.01,
        "trend_volume":p>e20 and vol>=1.5*va,
        "h1_reclaim":p>=e20 and p<=e20*1.01,
        "base_gate":p>avg*1.01 and vol>=1.5*va and ((res-(sup+sup*1.005)/2)/((sup+sup*1.005)/2-sup*.99) if sup>0 else 0)>=1
    }

def allowed(f,v):
    if v=="baseline": return f["base_gate"]
    return f["base_gate"] and f[v]

def collect(symbol,end):
    start=end-timedelta(days=30.44*18)
    h=fetch(H,symbol,start,end); d=fetch(D,symbol,start,end)
    out=[]
    for i in range(51,len(h)-HORIZON):
        o=outcome(h,i)
        if o is not None and daily_regime(d,h[i]["t"])=="BULL":
            out.append((h[i]["t"],o,regime_features(h,d,i)))
    return out

def passed(x):
    return x["trades"]>=30 and (x["profit_factor"] or 0)>1.05 and (x["expectancy_pct"] or -999)>0

def main():
    end=datetime.now(timezone.utc)
    events={s:collect(s,end) for s in TARGETS}
    n=min(len(v) for v in events.values())
    warm=n//5
    block=(n-warm)//4
    folds=[]
    for k in range(4):
        lo=warm+k*block
        hi=warm+(k+1)*block if k<3 else n
        train_start=warm
        shared_train={v:stats([events[s][i][1] for s in TARGETS for i in range(train_start,lo) if allowed(events[s][i][2],v)]) for v in VARIANTS}
        eligible=[(x["expectancy_pct"],x["profit_factor"],v) for v,x in shared_train.items()
                  if x["trades"]>=30 and (x["expectancy_pct"] or -999)>0 and (x["profit_factor"] or 0)>1]
        selected=max(eligible,default=(-999,-999,"baseline"))[2]
        shared_test={v:stats([events[s][i][1] for s in TARGETS for i in range(lo,hi) if allowed(events[s][i][2],v)]) for v in VARIANTS}
        folds.append({"fold":k+1,"train_end_index":lo,"test_end_index":hi,
                      "selected_variant":selected,"training":shared_train,
                      "test_all_variants":shared_test,"selected_test":shared_test[selected]})
    selected=[f["selected_variant"] for f in folds]
    selected_pass=[passed(f["selected_test"]) for f in folds]
    baseline=[passed(f["test_all_variants"]["baseline"]) for f in folds]
    out={"version":"7.5.0-regime-filter","production_changed":False,
         "purpose":"Test additional trend/regime conditioning without changing production",
         "period_months":18,"targets":TARGETS,"fold_count":4,
         "base_context":"1D BULL","horizon_hours":HORIZON,
         "variants":{
           "baseline":"existing momentum+volume+RR gate",
           "h1_trend":"baseline + 1H price > EMA20",
           "strong_1d":"baseline + 1D EMA20 > EMA50*1.005",
           "trend_momentum":"baseline + 1H price > EMA20 + price > 20H average*1.01",
           "trend_volume":"baseline + 1H price > EMA20 + volume >= 1.5x prior 20H average",
           "h1_reclaim":"baseline + price between 1H EMA20 and 1% above EMA20"},
         "split_rule":"expanding walk-forward: 20% initial warmup, then four chronological test folds; variant selected using prior data only",
         "holdout_rule":"trades>=30, PF>1.05, positive expectancy",
         "events_per_coin":{s:len(events[s]) for s in TARGETS},
         "folds":folds,"selected_variants_by_fold":selected,
         "selected_pass_by_fold":selected_pass,"selected_pass_count":sum(selected_pass),
         "baseline_pass_by_fold":baseline,"baseline_pass_count":sum(baseline)}
    open("v7_5_regime_filter_results.json","w").write(json.dumps(out,indent=2))
    print(json.dumps(out,indent=2))
if __name__=="__main__": main()
