#!/usr/bin/env python3
"""V7.6 research-only Coin Fingerprint pattern discovery.

Learns per-coin pre-move patterns from training data only, then checks them on
validation and a fully unseen chronological test period. Production is never changed.
"""
from __future__ import annotations
import json
from datetime import datetime,timedelta,timezone
from backtest_coin_specific import H,D,HORIZON,feat,fetch,daily_regime,outcome,ema

TARGETS=["BTCUSDT","ETHUSDT","SOLUSDT","XRPUSDT"]
HORIZONS=(6,12,24,48,72)
FEATURES=("rsi","vol_ratio","momentum_20","ema_distance","support_distance","range_20","btc_regime","h1_trend","d1_trend")

def feature_row(h,d,i,btc_d=None,btc_h=None):
    p,e20,e50,r,sup,res,avg,vol,va=feat(h,i)
    c=[x["c"] for x in h[i-50:i+1]]
    r20=p/c[-21] - 1 if len(c)>=21 else 0
    rows=[x for x in d if x["t"]<=h[i]["t"]]
    dc=[x["c"] for x in rows[-50:]]
    d20=ema(dc[-20:],20) if len(dc)>=20 else None
    d50=ema(dc,50) if len(dc)>=50 else None
    dr="BULL" if d20 and d50 and d20>d50*1.002 else "BEAR" if d20 and d50 and d20<d50*.998 else "SIDEWAYS"
    br="UNKNOWN"
    if btc_d is not None:
        br=daily_regime(btc_d,h[i]["t"])
    return {
      "rsi":r,"vol_ratio":vol/va if va else 0,"momentum_20":r20,
      "ema_distance":p/e20-1 if e20 else 0,
      "support_distance":(p-sup)/p if p else 0,
      "range_20":(res-sup)/p if p else 0,
      "btc_regime":br,"h1_trend":p>e20,"d1_trend":dr
    }

def forward(h,i,n):
    if i+1+n>=len(h): return None
    en=h[i]["c"]; z=h[i+1:i+1+n]
    return {"close":z[-1]["c"]/en-1,"max":max(x["h"] for x in z)/en-1,"min":min(x["l"] for x in z)/en-1}

def collect(symbol,start,end,btc_d=None):
    h=fetch(H,symbol,start,end); d=fetch(D,symbol,start,end)
    rows=[]
    for i in range(60,len(h)-73):
        fs=feature_row(h,d,i,btc_d)
        outs={str(n):forward(h,i,n) for n in HORIZONS}
        if all(v is not None for v in outs.values()):
            rows.append({"t":h[i]["t"],"features":fs,"outcomes":outs})
    return rows

def quantile_edges(vals,k=4):
    if not vals:return [0,1]
    s=sorted(vals); edges=[]
    for q in (0.25,0.5,0.75):
        edges.append(s[min(len(s)-1,int(q*(len(s)-1)))])
    return [-1e99]+edges+[1e99]

def bucket(x,edges):
    for i in range(len(edges)-1):
        if edges[i] <= x <= edges[i+1]: return i
    return len(edges)-2

def learn_patterns(rows):
    numeric=("rsi","vol_ratio","momentum_20","ema_distance","support_distance","range_20")
    edges={f:quantile_edges([r["features"][f] for r in rows]) for f in numeric}
    candidates=[]
    labels=[]
    for r in rows:
        key=[]
        for f in numeric:key.append((f,bucket(r["features"][f],edges[f])))
        for f in ("h1_trend","d1_trend","btc_regime"):
            key.append((f,str(r["features"][f])))
        candidates.append((r,tuple(key)))
    # One-feature and two-feature patterns; require enough support.
    for f in numeric:
        for b in range(4):
            labels.append(((f,b),lambda r,f=f,b=b: bucket(r["features"][f],edges[f])==b))
    for f in ("h1_trend","d1_trend","btc_regime"):
        vals=sorted(set(str(r["features"][f]) for r in rows))
        for v in vals: labels.append(((f,v),lambda r,f=f,v=v: str(r["features"][f])==v))
    for a,b in ((("rsi"),("vol_ratio")),(("momentum_20"),("vol_ratio")),(("ema_distance"),("h1_trend")),(("rsi"),("h1_trend"))):
        if a in numeric and b in numeric:
            for ia in range(4):
                for ib in range(4):
                    labels.append((((a,ia),(b,ib)),lambda r,a=a,b=b,ia=ia,ib=ib: bucket(r["features"][a],edges[a])==ia and bucket(r["features"][b],edges[b])==ib))
    patterns=[]
    for label,fn in labels:
        matched=[r for r in rows if fn(r)]
        if len(matched)<40:continue
        for horizon in ("24","48"):
            up=sum(1 for r in matched if r["outcomes"][horizon]["max"]>=0.02)/len(matched)
            down=sum(1 for r in matched if r["outcomes"][horizon]["min"]<=-0.02)/len(matched)
            avg=sum(r["outcomes"][horizon]["close"] for r in matched)/len(matched)
            # Require directional separation from the full training population.
            patterns.append({"label":label,"horizon":int(horizon),"n":len(matched),"up_rate":up,"down_rate":down,"avg_close":avg})
    base={}
    for horizon in ("24","48"):
        base[horizon]={"up_rate":sum(r["outcomes"][horizon]["max"]>=.02 for r in rows)/len(rows),
                       "down_rate":sum(r["outcomes"][horizon]["min"]<=-.02 for r in rows)/len(rows),
                       "avg_close":sum(r["outcomes"][horizon]["close"] for r in rows)/len(rows)}
    patterns.sort(key=lambda x:(abs(x["up_rate"]-base[str(x["horizon"])]["up_rate"])+abs(x["down_rate"]-base[str(x["horizon"])]["down_rate"]),x["n"]),reverse=True)
    return {"edges":edges,"baseline":base,"patterns":patterns[:30]}

def eval_pattern(rows,p):
    label=p["label"]; horizon=str(p["horizon"])
    def ok(r):
        for item in label:
            f,v=item
            if f in ("h1_trend","d1_trend","btc_regime"):
                if str(r["features"][f])!=str(v):return False
            else:
                # edges are reconstructed by using learned bucket ids stored in label only;
                # evaluation label includes bucket ids and needs edges from training.
                return False
        return True
    return None

def apply_patterns(rows,learned):
    edges=learned["edges"]; out=[]
    for p in learned["patterns"][:10]:
        matched=[]
        for r in rows:
            ok=True
            for item in p["label"]:
                f,v=item
                if f in ("h1_trend","d1_trend","btc_regime"):
                    ok &= str(r["features"][f])==str(v)
                else:
                    ok &= bucket(r["features"][f],edges[f])==int(v)
            if ok:matched.append(r)
        if matched:
            h=str(p["horizon"])
            out.append({"label":p["label"],"horizon":p["horizon"],"n":len(matched),
                        "up_rate":sum(r["outcomes"][h]["max"]>=.02 for r in matched)/len(matched),
                        "down_rate":sum(r["outcomes"][h]["min"]<=-.02 for r in matched)/len(matched),
                        "avg_close":sum(r["outcomes"][h]["close"] for r in matched)/len(matched)})
    return out

def summarize(rows):
    return {str(h):{"n":len(rows),"up_rate":sum(r["outcomes"][str(h)]["max"]>=.02 for r in rows)/len(rows),
                    "down_rate":sum(r["outcomes"][str(h)]["min"]<=-.02 for r in rows)/len(rows),
                    "avg_close":sum(r["outcomes"][str(h)]["close"] for r in rows)/len(rows)} for h in HORIZONS}

def main():
    end=datetime.now(timezone.utc); start=end-timedelta(days=30.44*18)
    btc_d=fetch(D,"BTCUSDT",start,end)
    events={s:collect(s,start,end,btc_d) for s in TARGETS}
    results={}
    for s,rows in events.items():
        n=len(rows); a=int(n*.20); b=int(n*.60)
        train=rows[:a]; valid=rows[a:b]; test=rows[b:]
        learned=learn_patterns(train)
        valid_patterns=apply_patterns(valid,learned)
        test_patterns=apply_patterns(test,learned)
        results[s]={"events":n,"split":{"train":len(train),"validation":len(valid),"unseen_test":len(test)},
                    "overall":summarize(rows),"train":summarize(train),"validation":summarize(valid),"unseen_test":summarize(test),
                    "top_training_patterns":learned["patterns"][:10],
                    "validation_pattern_results":valid_patterns,
                    "unseen_pattern_results":test_patterns}
    out={"version":"7.6.0-coin-fingerprint","production_changed":False,
         "purpose":"Discover per-coin pre-move patterns and test them on unseen chronological data",
         "period_months":18,"targets":TARGETS,"horizons_hours":list(HORIZONS),
         "labels":"up if future max >= +2%; down if future min <= -2%; close return also measured",
         "split_rule":"chronological 20% train, 40% validation, 40% unseen test; patterns learned from train only",
         "pattern_features":list(FEATURES),
         "results":results}
    open("v7_6_coin_fingerprint_results.json","w").write(json.dumps(out,indent=2));print(json.dumps(out,indent=2))
if __name__=="__main__":main()

# V7.6 trigger verification
