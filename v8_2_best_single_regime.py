import json
from datetime import datetime,timedelta,timezone
from backtest_coin_specific import H,fetch,feat
from app.crypto.strategy import generate_signal

TARGETS=["BTCUSDT","ETHUSDT","SOLUSDT","XRPUSDT"]
HORIZON=24
DIMS=["coin_trend","momentum","volume","volatility"]

def outcome(h,i):
    z=h[i+1:i+1+HORIZON]
    if len(z)<HORIZON:return None
    en=h[i]["c"]
    return {"ret":z[-1]["c"]/en-1}

def event(h,i):
    p,e20,e50,r,sup,res,avg,vol,va=feat(h,i)
    vr=vol/va if va else None
    mom=p/h[i-6]["c"]-1
    sig=generate_signal(rsi=r,ema20=e20,ema50=e50,price=p,support=sup,
                         resistance=res,volume_ratio=vr,momentum_6h=mom)
    if sig["signal"] not in ("BUY SETUP","STRONG BUY"):
        return None
    rng=(max(x["h"] for x in h[i-19:i+1])-min(x["l"] for x in h[i-19:i+1]))/p
    state={
        "coin_trend":"BULL" if e20>e50 else "NON_BULL",
        "momentum":"NEGATIVE" if mom<0 else ("0_TO_1PCT" if mom<.01 else "ABOVE_1PCT"),
        "volume":"BELOW_AVG" if vr is None or vr<1 else ("1_TO_1_5X" if vr<1.5 else "ABOVE_1_5X"),
        "volatility":"LOW" if rng<.02 else ("NORMAL" if rng<.05 else "HIGH")
    }
    return {"state":state,"o":outcome(h,i)}

def metrics(rows):
    v=[x["o"]["ret"] for x in rows if x.get("o")]
    if not v:return {"trades":0,"expectancy_pct":None,"pf":None,"win_rate_pct":None}
    wins=[x for x in v if x>0]
    losses=[-x for x in v if x<=0]
    return {"trades":len(v),"win_rate_pct":round(100*len(wins)/len(v),2),
            "expectancy_pct":round(100*sum(v)/len(v),4),
            "pf":round(sum(wins)/sum(losses),3) if losses else None}

def good(x):
    return x["trades"]>=10 and (x["pf"] or 0)>1.05 and (x["expectancy_pct"] or -999)>0

def main():
    end=datetime.now(timezone.utc)
    start=end-timedelta(days=30.44*18)
    out={"version":"8.2.0-best-single-regime-walk-forward","production_changed":False,
         "selection":"prior-fold only; choose one regime dimension from prior data; no future information",
         "results":{}}
    for coin in TARGETS:
        h=fetch(H,coin,start,end)
        ev=[event(h,i) for i in range(60,len(h)-HORIZON-1)]
        ev=[x for x in ev if x]
        n=len(ev); warm=max(1,int(n*.20)); block=max(1,(n-warm)//4)
        folds=[]
        for f in range(4):
            train_end=warm+f*block
            test_end=warm+(f+1)*block if f<3 else n
            train=ev[:train_end]; test=ev[train_end:test_end]
            candidates=[]
            for dim in DIMS:
                for bucket in sorted({x["state"][dim] for x in train}):
                    mm=metrics([x for x in train if x["state"][dim]==bucket])
                    if good(mm):
                        candidates.append({"dim":dim,"bucket":bucket,"train":mm})
            if candidates:
                # deterministic tie-break: expectancy, PF, then trades
                chosen=max(candidates,key=lambda x:((x["train"]["expectancy_pct"] or -999),
                                                    (x["train"]["pf"] or 0),
                                                    x["train"]["trades"]))
            else:
                chosen=None
            if chosen:
                filtered=[x for x in test if x["state"][chosen["dim"]]==chosen["bucket"]]
            else:
                filtered=[]
            folds.append({"fold":f+1,"train_events":len(train),"test_events":len(test),
                          "selected_regime":chosen,
                          "baseline":metrics(test),"regime_filtered":metrics(filtered)})
        out["results"][coin]={"production_buy_signals":n,"folds":folds,
                              "baseline_passes":sum(good(x["baseline"]) for x in folds),
                              "filtered_passes":sum(good(x["regime_filtered"]) for x in folds)}
    open("v8_2_best_single_regime_results.json","w").write(json.dumps(out,indent=2))
    print(json.dumps(out,indent=2))

if __name__=="__main__":
    main()
