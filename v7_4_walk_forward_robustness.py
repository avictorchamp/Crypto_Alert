#!/usr/bin/env python3
"""V7.4 research-only expanding walk-forward gate robustness experiment."""
from __future__ import annotations
import json
from datetime import datetime, timedelta, timezone
from backtest_coin_specific import H, D, HORIZON, feat, fetch, daily_regime, outcome

TARGETS = ["BTCUSDT","ETHUSDT","SOLUSDT","XRPUSDT"]
VARIANTS = ("baseline","price_relaxed","volume_relaxed","price_only","volume_only","both_relaxed")

def gate(x, variant):
    p,e20,e50,r,sup,res,avg,vol,va=x
    mid=(sup+sup*1.005)/2
    rr=(res-mid)/(mid-sup*0.99) if sup>0 else 0
    return {
        "baseline": p>avg*1.01 and vol>=1.5*va and rr>=1,
        "price_relaxed": p>avg*1.005 and vol>=1.5*va and rr>=1,
        "volume_relaxed": p>avg*1.01 and vol>=1.2*va and rr>=1,
        "price_only": p>avg*1.01 and rr>=1,
        "volume_only": vol>=1.5*va and rr>=1,
        "both_relaxed": p>avg*1.005 and vol>=1.2*va and rr>=1,
    }[variant]

def stats(rows):
    if not rows:
        return {"trades":0,"win_rate_pct":None,"expectancy_pct":None,"profit_factor":None}
    r=[z[0] for z in rows]; wins=[z for z in r if z>0]; loss=-sum(z for z in r if z<0)
    pf=sum(wins)/loss if loss else None
    return {"trades":len(r),"win_rate_pct":round(100*len(wins)/len(r),2),
            "expectancy_pct":round(100*sum(r)/len(r),4),
            "profit_factor":round(pf,3) if pf is not None else None}

def collect(symbol,end):
    start=end-timedelta(days=30.44*18)
    h=fetch(H,symbol,start,end); d=fetch(D,symbol,start,end)
    out=[]
    for i in range(51,len(h)-HORIZON):
        o=outcome(h,i)
        if o is not None and daily_regime(d,h[i]["t"])=="BULL":
            out.append((h[i]["t"],o,feat(h,i)))
    return out

def select(scores):
    eligible=[(s["expectancy_pct"],s["profit_factor"],v) for v,s in scores.items()
              if s["trades"]>=30 and (s["expectancy_pct"] or -999)>0 and (s["profit_factor"] or 0)>1]
    return max(eligible, default=(-999,-999,"baseline"))[2]

def main():
    end=datetime.now(timezone.utc)
    events={s:collect(s,end) for s in TARGETS}
    n=min(len(v) for v in events.values())
    # Four chronological test folds after a 20% initial training window.
    warm=n//5
    test_size=(n-warm)//4
    folds=[]
    for k in range(4):
        test_start=warm+k*test_size
        test_end=warm+(k+1)*test_size if k<3 else n
        shared_train={}
        coin_train={}
        for v in VARIANTS:
            rows=[]
            for s in TARGETS:
                rows += [events[s][i][1] for i in range(warm,test_start) if gate(events[s][i][2],v)]
            shared_train[v]=stats(rows)
        for s in TARGETS:
            coin_train[s]={v:stats([events[s][i][1] for i in range(warm,test_start) if gate(events[s][i][2],v)]) for v in VARIANTS}
        shared=select(shared_train)
        coin={s:select(coin_train[s]) for s in TARGETS}
        shared_rows=[events[s][i][1] for s in TARGETS for i in range(test_start,test_end) if gate(events[s][i][2],shared)]
        shared_test=stats(shared_rows)
        coin_test={s:stats([events[s][i][1] for i in range(test_start,test_end) if gate(events[s][i][2],coin[s])]) for s in TARGETS}
        baseline={s:stats([events[s][i][1] for i in range(test_start,test_end) if gate(events[s][i][2],"baseline")]) for s in TARGETS}
        folds.append({"fold":k+1,"train_start":warm,"test_start":test_start,"test_end":test_end,
                      "shared_variant":shared,"coin_specific_variants":coin,
                      "shared_test":shared_test,"coin_specific_test":coin_test,"baseline_test":baseline})
    def passed(x):
        return x["trades"]>=30 and (x["profit_factor"] or 0)>1.05 and (x["expectancy_pct"] or -999)>0
    shared_pass=[passed(f["shared_test"]) for f in folds]
    coin_pass={s:[passed(f["coin_specific_test"][s]) for f in folds] for s in TARGETS}
    baseline_pass={s:[passed(f["baseline_test"][s]) for f in folds] for s in TARGETS}
    out={"version":"7.4.0-walk-forward-robustness","production_changed":False,
         "period_months":18,"targets":TARGETS,"fold_count":4,
         "split_rule":"expanding training: 20% initial warmup, then four chronological test folds; each gate selected using prior data only",
         "holdout_rule":"trades>=30, PF>1.05, positive expectancy",
         "events_per_coin":{s:len(events[s]) for s in TARGETS},
         "folds":folds,"shared_pass_by_fold":shared_pass,
         "shared_pass_count":sum(shared_pass),"coin_specific_pass_by_fold":coin_pass,
         "coin_specific_pass_count":{s:sum(v) for s,v in coin_pass.items()},
         "baseline_pass_by_fold":baseline_pass,"baseline_pass_count":{s:sum(v) for s,v in baseline_pass.items()},
         "shared_all_folds":all(shared_pass),
         "coin_specific_all_folds":{s:all(v) for s,v in coin_pass.items()},
         "baseline_all_folds":{s:all(v) for s,v in baseline_pass.items()}}
    print(json.dumps(out,indent=2))
    with open("v7_4_walk_forward_robustness_results.json","w") as f: json.dump(out,f,indent=2)

if __name__=="__main__": main()
