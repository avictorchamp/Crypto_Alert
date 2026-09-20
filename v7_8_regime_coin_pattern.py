#!/usr/bin/env python3
"""V7.8 research-only Regime x Coin Pattern validation.

Learns the best coin-specific regime-conditioned variant from prior chronological
data only, then evaluates it on the next unseen fold. Production is unchanged.
"""
import json
from datetime import datetime,timedelta,timezone
from backtest_coin_specific import H,D,feat,fetch,daily_regime

TARGETS=["BTCUSDT","ETHUSDT","SOLUSDT","XRPUSDT"]
HORIZON=24

def row(h,d,i,btc_d):
    p,e20,e50,r,sup,res,avg,vol,va=feat(h,i)
    c=h[i]["c"]
    m20=c/h[i-20]["c"]-1
    vol_ratio=vol/va if va else 0
    return {
      "t":h[i]["t"],"p":p,"rsi":r,"vol_ratio":vol_ratio,"mom":m20,
      "ema_dist":p/e20-1 if e20 else 0,"h1":p>e20,
      "d1":daily_regime(d,h[i]["t"]),"btc":daily_regime(btc_d,h[i]["t"])
    }

def outcome(h,i):
    z=h[i+1:i+1+HORIZON]
    if len(z)<HORIZON:return None
    en=h[i]["c"]
    return {"ret":z[-1]["c"]/en-1,"mfe":max(x["h"] for x in z)/en-1,
            "mae":min(x["l"] for x in z)/en-1}

def collect(symbol,start,end,btc_d):
    h=fetch(H,symbol,start,end); d=fetch(D,symbol,start,end)
    out=[]
    for i in range(60,len(h)-HORIZON-1):
        o=outcome(h,i)
        if o: out.append({"x":row(h,d,i,btc_d),"o":o})
    return out

def base(x):
    return x["d1"]=="BULL" and x["h1"] and x["mom"]>.01 and x["vol_ratio"]>=1.2

def variants(x):
    g=base(x)
    return {
      "baseline":g,
      "btc_bull":g and x["btc"]=="BULL",
      "high_vol":g and x["vol_ratio"]>=1.5,
      "strong_momentum":g and x["mom"]>.015,
      "coin_trend":g and x["ema_dist"]>0,
      "btc_bull_coin_trend":g and x["btc"]=="BULL" and x["ema_dist"]>0,
      "high_vol_strong_momentum":g and x["vol_ratio"]>=1.5 and x["mom"]>.015,
      "btc_bull_high_vol":g and x["btc"]=="BULL" and x["vol_ratio"]>=1.5,
      "btc_bull_strong_momentum":g and x["btc"]=="BULL" and x["mom"]>.015,
      "trend_volume":g and x["ema_dist"]>0 and x["vol_ratio"]>=1.5,
    }

def metrics(rows):
    n=len(rows)
    if not n:return {"trades":0,"win_rate":None,"expectancy":None,"pf":None}
    vals=[r["o"]["ret"] for r in rows]
    wins=[v for v in vals if v>0]; losses=[-v for v in vals if v<=0]
    return {"trades":n,"win_rate":sum(v>0 for v in vals)/n,
            "expectancy":sum(vals)/n,"pf":sum(wins)/sum(losses) if losses else None}

def evalv(rows,name):
    return metrics([r for r in rows if variants(r["x"])[name]])

def regime_stats(rows):
    keys={}
    for r in rows:
        x=r["x"]; key=f'{x["d1"]}|BTC:{x["btc"]}|H1:{"UP" if x["h1"] else "DOWN"}|VOL:{"HIGH" if x["vol_ratio"]>=1.5 else "NORMAL"}'
        keys.setdefault(key,[]).append(r)
    return {k:metrics(v) for k,v in sorted(keys.items())}

def main():
    end=datetime.now(timezone.utc); start=end-timedelta(days=30.44*18)
    btc_d=fetch(D,"BTCUSDT",start,end)
    allr={s:collect(s,start,end,btc_d) for s in TARGETS}
    results={}
    for s,rs in allr.items():
        n=len(rs); folds=[]
        for k in range(4):
            cut=int(n*.20)+int(k*(n*.80/4))
            nxt=int(n*.20)+int((k+1)*(n*.80/4))
            train=rs[:cut]; test=rs[cut:nxt]
            names=list(variants(rs[0]["x"]).keys())
            scores={v:evalv(train,v) for v in names}
            eligible=[v for v,m in scores.items()
                       if m["trades"]>=30 and m["expectancy"]>0 and (m["pf"] or 0)>1]
            selected=max(eligible,key=lambda v:(scores[v]["expectancy"],scores[v]["pf"])) if eligible else "baseline"
            folds.append({
              "fold":k+1,"train":len(train),"test":len(test),"selected":selected,
              "selected_test":evalv(test,selected),"baseline_test":evalv(test,"baseline"),
              "training_scores":scores,"test_regime_stats":regime_stats(test)
            })
        results[s]={"events":n,"folds":folds}
    out={
      "version":"7.8.0-regime-x-coin-pattern",
      "production_changed":False,
      "purpose":"Test whether coin-specific entry variants become more stable when conditioned on market and coin regime",
      "period_months":18,"horizon_hours":24,
      "split":"4 expanding chronological folds; each variant is selected from prior data only",
      "base_gate":"1D BULL + 1H trend + 20h momentum > 1% + volume ratio >= 1.2",
      "variants":list(variants(allr[TARGETS[0]][0]["x"]).keys()),
      "pass":"trades>=30, PF>1.05, expectancy>0",
      "results":results
    }
    open("v7_8_regime_coin_pattern_results.json","w").write(json.dumps(out,indent=2))
    print(json.dumps(out,indent=2))
if __name__=="__main__": main()
