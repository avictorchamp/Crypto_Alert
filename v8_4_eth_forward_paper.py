#!/usr/bin/env python3
"""V8.4 ETH forward paper validation. Research only; never trades live."""
from __future__ import annotations
import json, os
from datetime import datetime, timezone
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from app.crypto.strategy import generate_signal
from app.crypto.indicators import calculate_ema, calculate_rsi, support_resistance

SYMBOL="ETHUSDT"
HORIZON_HOURS=24
VOLUME_THRESHOLD=1.5
LOG_FILE="v8_4_eth_forward_log.json"
FEE=0.001
SLIPPAGE=0.0005

def fetch_klines(limit=120):
    last=None
    for host in ("api.binance.com","api.binance.us"):
        url=f"https://{host}/api/v3/klines?symbol={SYMBOL}&interval=1h&limit={limit}"
        try:
            with urlopen(Request(url,headers={"User-Agent":"CryptoAlert-V8.4-Paper"}),timeout=30) as r:
                return json.loads(r.read().decode())
        except HTTPError as e:
            last=e
            if e.code not in (403,404,429,451): raise
    raise RuntimeError(f"Binance API unavailable: {last}")

def metrics(rows):
    closed=[float(x["paper_return_pct"]) for x in rows if x.get("status")=="CLOSED"]
    wins=[x for x in closed if x>0]; losses=[-x for x in closed if x<=0]
    n=len(closed)
    return {
        "closed_trades":n,
        "winning_trades":len(wins),
        "losing_trades":len(losses),
        "win_rate_pct":round(100*len(wins)/n,2) if n else None,
        "expectancy_pct":round(sum(closed)/n,4) if n else None,
        "profit_factor":round(sum(wins)/sum(losses),3) if losses else None,
        "open_trades":sum(x.get("status")=="OPEN" for x in rows),
    }

def main():
    raw=fetch_klines()
    # Binance returns the currently forming candle last; use only completed candles.
    candles=[{
        "t":int(x[0]),"o":float(x[1]),"h":float(x[2]),"l":float(x[3]),
        "c":float(x[4]),"v":float(x[5])
    } for x in raw]
    now_ms=int(datetime.now(timezone.utc).timestamp()*1000)
    completed=[x for x in candles if x["t"]+3600000<=now_ms]
    if len(completed)<101: raise RuntimeError(f"insufficient completed 1H candles: {len(completed)}")

    data={"version":"8.4.0-eth-forward-paper","production_changed":False,
          "symbol":SYMBOL,"horizon_hours":HORIZON_HOURS,
          "locked_rule":{"strategy":"exact production BUY SETUP or STRONG BUY",
                         "volume_condition":"volume_ratio > 1.5",
                         "volume_threshold":VOLUME_THRESHOLD},
          "observations":[]}
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE,encoding="utf-8") as f:data=json.load(f)
        assert data.get("production_changed") is False
        assert data.get("locked_rule",{}).get("volume_threshold")==VOLUME_THRESHOLD
    obs=data.setdefault("observations",[])
    known={int(x["signal_candle_close_ms"]) for x in obs}

    # Reproduce production market inputs from the latest 100 completed 1H candles.
    window=completed[-100:]
    prices=[x["c"] for x in window]
    price=prices[-1]
    rsi=calculate_rsi(prices)
    ema20=calculate_ema(prices,20)
    ema50=calculate_ema(prices,50)
    support,resistance=support_resistance(prices)
    avg_prev20=sum(x["v"] for x in window[-21:-1])/20
    volume_ratio=window[-1]["v"]/avg_prev20 if avg_prev20 else None
    momentum_6h=price/window[-7]["c"]-1 if window[-7]["c"] else None
    sig=generate_signal(rsi=rsi,ema20=ema20,ema50=ema50,price=price,
                        support=support,resistance=resistance,
                        volume_ratio=volume_ratio,momentum_6h=momentum_6h)
    candle_close_ms=window[-1]["t"]+3600000

    if candle_close_ms not in known:
        row={"signal_time_utc":datetime.fromtimestamp(candle_close_ms/1000,timezone.utc).isoformat(),
             "signal_candle_close_ms":candle_close_ms,"price":price,
             "signal":sig["signal"],"confidence":sig["confidence"],
             "quality_score":sig["quality_score"],"risk_reward":sig["risk_reward"],
             "volume_ratio":volume_ratio,"momentum_6h":momentum_6h}
        row["locked_entry"]=sig["signal"] in ("BUY SETUP","STRONG BUY") and volume_ratio is not None and volume_ratio>VOLUME_THRESHOLD
        row["status"]="OPEN" if row["locked_entry"] else "NO_TRADE"
        obs.append(row)

    # Close 24h paper trades when a completed candle is available.
    by={x["t"]:x for x in completed}
    for row in obs:
        if row.get("status")!="OPEN": continue
        target=int(row["signal_candle_close_ms"])+HORIZON_HOURS*3600000
        future=[t for t in by if t>=target]
        if not future: continue
        exit_c=by[min(future)]["c"]
        gross=(exit_c/float(row["price"])-1)*100
        row.update({"exit_time_utc":datetime.fromtimestamp(min(future)/1000,timezone.utc).isoformat(),
                    "exit_price":exit_c,
                    "paper_return_pct":round(gross-(FEE+SLIPPAGE)*100,4),
                    "status":"CLOSED"})

    obs.sort(key=lambda x:int(x["signal_candle_close_ms"]))
    data["latest_signal_utc"]=obs[-1]["signal_time_utc"] if obs else None
    data["last_run_utc"]=datetime.now(timezone.utc).isoformat()
    data["candles_1h_completed"]=len(completed)
    data["summary"]=metrics(obs)
    with open(LOG_FILE,"w",encoding="utf-8") as f:json.dump(data,f,indent=2)
    print(json.dumps({"latest_signal_utc":data["latest_signal_utc"],
                      "latest_signal":obs[-1]["signal"] if obs else None,
                      "latest_locked_entry":obs[-1]["locked_entry"] if obs else None,
                      "latest_volume_ratio":obs[-1]["volume_ratio"] if obs else None,
                      "summary":data["summary"],"production_changed":False},indent=2))

if __name__=="__main__": main()
