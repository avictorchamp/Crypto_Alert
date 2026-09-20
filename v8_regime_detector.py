import json
from datetime import datetime,timedelta,timezone
from backtest_coin_specific import H,fetch,feat
from app.crypto.strategy import generate_signal

TARGETS=["BTCUSDT","ETHUSDT","SOLUSDT","XRPUSDT"]
HORIZON=24

def outcome(h,i):
    z=h[i+1:i+1+HORIZON]
    if len(z)<HORIZON:return None
    en=h[i]["c"]
    vals=[x["c"]/en-1 for x in z]
    return {"ret":vals[-1],"mfe":max(x["h"] for x in z)/en-1,"mae":min(x["l"] for x in z)/en-1}

def signal_and_state(h,i):
    p,e20,e50,r,sup,res,avg,vol,va=feat(h,i)
    vr=vol/va if va else None
    mom=(p/h[i-6]["c"]-1) if h[i-6]["c"] else None
    sig=generate_signal(rsi=r,ema20=e20,ema50=e50,price=p,support=sup,resistance=res,volume_ratio=vr,momentum_6h=mom)
    rng=(max(x["h"] for x in h[i-19:i+1])-min(x["l"] for x in h[i-19:i+1]))/p if p else 0
    if rng<0.02: vol_regime="LOW"
    elif rng<0.05: vol_regime="NORMAL"
    else: vol_regime="HIGH"
    if mom<0: mom_regime="NEGATIVE"
    elif mom<0.01: mom_regime="0_TO_1PCT"
    else: mom_regime="ABOVE_1PCT"
    if vr is None or vr<1: volume_regime="BELOW_AVG"
    elif vr<1.5: volume_regime="1_TO_1_5X"
    else: volume_regime="ABOVE_1_5X"
    return sig["signal"],{
        "coin_trend":"BULL" if e20>e50 else "NON_BULL",
        "momentum":mom_regime,
        "volume":volume_regime,
        "volatility":vol_regime,
    }

def metrics(rows):
    vals=[x["o"]["ret"] for x in rows]
    if not vals:return {"trades":0,"win_rate_pct":None,"expectancy_pct":None,"pf":None}
    wins=[v for v in vals if v>0]; losses=[-v for v in vals if v<=0]
    return {"trades":len(vals),"win_rate_pct":round(100*len(wins)/len(vals),2),
            "expectancy_pct":round(100*sum(vals)/len(vals),4),
            "pf":round(sum(wins)/sum(losses),3) if losses else None}

def main():
    end=datetime.now(timezone.utc); start=end-timedelta(days=30.44*18)
    out={"version":"8.0.0-regime-detector","production_changed":False,
         "period_months":18,"horizon_hours":24,
         "method":"exact production generate_signal; descriptive regime buckets; no tuning or variant selection",
         "dimensions":["coin_trend","momentum","volume","volatility"],"results":{}}
    for s in TARGETS:
        h=fetch(H,s,start,end)
        events=[]
        for i in range(60,len(h)-HORIZON-1):
            o=outcome(h,i)
            if not o: continue
            sig,state=signal_and_state(h,i)
            if sig in ("BUY SETUP","STRONG BUY"):
                events.append({"t":h[i]["t"],"state":state,"o":o})
        n=len(events); warm=int(n*.20); block=max(1,(n-warm)//4)
        dims={}
        for dim in out["dimensions"]:
            buckets=sorted({e["state"][dim] for e in events})
            dims[dim]={}
            for bucket in buckets:
                folds=[]
                for f in range(4):
                    lo=warm+f*block; hi=warm+(f+1)*block if f<3 else n
                    test=[e for e in events[lo:hi] if e["state"][dim]==bucket]
                    m=metrics(test); folds.append({"fold":f+1,**m})
                positive=[x for x in folds if x["trades"]>=10 and (x["pf"] or 0)>1.05 and (x["expectancy_pct"] or -999)>0]
                combined=metrics([e for e in events[warm:] if e["state"][dim]==bucket])
                dims[dim][bucket]={"folds":folds,"combined_test":combined,
                    "stable_3_of_4":len(positive)>=3}
        # Fixed two-way profile: trend x volatility, still descriptive and not selected.
        profile={}
        for trend in ("BULL","NON_BULL"):
            for vol in ("LOW","NORMAL","HIGH"):
                key=f"{trend}__{vol}"
                rows=[e for e in events[warm:] if e["state"]["coin_trend"]==trend and e["state"]["volatility"]==vol]
                profile[key]=metrics(rows)
        out["results"][s]={"production_buy_signals":n,"fold_definition":"20% warmup + 4 chronological unseen folds",
                            "regime_dimensions":dims,"trend_x_volatility":profile}
    open("v8_regime_detector_results.json","w").write(json.dumps(out,indent=2))
    print(json.dumps(out,indent=2))

if __name__=="__main__": main()
