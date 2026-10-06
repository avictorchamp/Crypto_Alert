"""V7.17 live XRP alert integration. Read-only; no order execution."""
import time
from app.telegram.bot import send_message

COOLDOWN=48*3600
_last_sent=0.0

def bucket(x, edges):
    for i in range(len(edges)-1):
        if edges[i] <= x <= edges[i+1]: return i
    return len(edges)-2

def quantile_edges(vals):
    s=sorted(vals)
    if not s: raise ValueError("no training values")
    q=[s[min(len(s)-1,int(p*(len(s)-1)))] for p in (.25,.5,.75)]
    return [-1e99]+q+[1e99]

def derive_edges(training_candles):
    """Reproduce V7.6/V7.15 quartile bucketing from chronological training candles."""
    moms=[]; vols=[]
    for i in range(20,len(training_candles)):
        closes=[float(x[4]) for x in training_candles[:i+1]]
        vv=[float(x[5]) for x in training_candles[:i+1]]
        if closes[-21] and sum(vv[-21:-1])>0:
            moms.append(closes[-1]/closes[-21]-1)
            vols.append(vv[-1]/(sum(vv[-21:-1])/20))
    return {"momentum_20":quantile_edges(moms),"vol_ratio":quantile_edges(vols)}

def live_features(candles):
    if len(candles)<21: raise ValueError("need >=21 candles")
    closes=[float(x[4]) for x in candles]; vols=[float(x[5]) for x in candles]
    avg=sum(vols[-21:-1])/20
    return {"price":closes[-1],"momentum_20":closes[-1]/closes[-21]-1,"vol_ratio":vols[-1]/avg}

def evaluate(features,edges):
    mb=bucket(features["momentum_20"],edges["momentum_20"])
    vb=bucket(features["vol_ratio"],edges["vol_ratio"])
    return mb==0 and vb==3,{"momentum_20_bucket":mb,"vol_ratio_bucket":vb}

def process_xrp_live(candles,edges,now=None,send=True):
    global _last_sent
    now=time.time() if now is None else now
    f=live_features(candles); matched,b=evaluate(f,edges)
    remaining=max(0,int(COOLDOWN-(now-_last_sent))) if _last_sent else 0
    emitted=bool(matched and remaining==0)
    if emitted and send:
        send_message(f"""🟢 XRP V7.15 VALIDATED ALERT

XRP/USDT
Signal: LONG
Research horizon: 48h
Price: {f['price']:.6f}
momentum_20 bucket: {b['momentum_20_bucket']}
vol_ratio bucket: {b['vol_ratio_bucket']}

Source: V7.15 final gate
Mode: ALERT ONLY / MANUAL EXECUTION
No automatic trading.""")
        _last_sent=now
    return {"symbol":"XRPUSDT","matched":matched,"sent":emitted and send,"features":f,"buckets":b,"cooldown_remaining":remaining,"automatic_trading":False}
