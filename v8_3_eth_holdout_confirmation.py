import json
from datetime import datetime, timezone
from backtest_coin_specific import H, fetch, feat
from app.crypto.strategy import generate_signal

COIN="ETHUSDT"
START=datetime(2024,9,22,tzinfo=timezone.utc)
END=datetime(2025,3,22,tzinfo=timezone.utc)
HORIZON=24
VOLUME_THRESHOLD=1.5

def outcome(h,i):
    z=h[i+1:i+1+HORIZON]
    if len(z)<HORIZON:
        return None
    entry=z[0]["o"]
    return z[-1]["c"]/entry-1

def event(h,i):
    p,e20,e50,r,sup,res,avg,vol,va=feat(h,i)
    vr=vol/va if va else None
    mom=p/h[i-6]["c"]-1
    sig=generate_signal(rsi=r,ema20=e20,ema50=e50,price=p,support=sup,
                         resistance=res,volume_ratio=vr,momentum_6h=mom)
    if sig["signal"] not in ("BUY SETUP","STRONG BUY"):
        return None
    o=outcome(h,i)
    if o is None:
        return None
    return {"volume_ratio":vr,"return":o}

def metrics(rows):
    vals=[x["return"] for x in rows]
    if not vals:
        return {"trades":0,"win_rate_pct":None,"expectancy_pct":None,"pf":None}
    wins=[x for x in vals if x>0]
    losses=[-x for x in vals if x<=0]
    return {
        "trades":len(vals),
        "win_rate_pct":round(100*len(wins)/len(vals),2),
        "expectancy_pct":round(100*sum(vals)/len(vals),4),
        "pf":round(sum(wins)/sum(losses),3) if losses else None
    }

def main():
    h=fetch(H,COIN,START,END)
    events=[event(h,i) for i in range(51,len(h)-HORIZON-1)]
    events=[x for x in events if x]
    baseline=events
    locked=[x for x in events if x["volume_ratio"] is not None and x["volume_ratio"]>VOLUME_THRESHOLD]
    out={
      "version":"8.3.0-eth-untouched-holdout",
      "production_changed":False,
      "coin":COIN,
      "selection":"LOCKED BEFORE TEST; no tuning on holdout",
      "locked_rule":{
        "strategy":"exact production BUY SETUP or STRONG BUY",
        "volume_threshold":VOLUME_THRESHOLD,
        "volume_condition":"volume_ratio > 1.5",
        "horizon_hours":HORIZON
      },
      "holdout":{
        "period_start":"2024-09-22",
        "period_end":"2025-03-22",
        "candles_1h":len(h),
        "production_buy_signals":len(baseline),
        "locked_signals":len(locked),
        "horizon_hours":HORIZON,
        "baseline":metrics(baseline),
        "locked":metrics(locked)
      }
    }
    open("v8_3_eth_holdout_results.json","w").write(json.dumps(out,indent=2))
    print(json.dumps(out,indent=2))

if __name__=="__main__":
    main()
