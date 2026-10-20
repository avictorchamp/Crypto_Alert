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

def fetch_klines(limit=1000):
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

def historical_signal_diagnostics(completed):
    """Count exact production-rule signals over rolling completed 1H windows.
    Signal-frequency diagnostics only; this does not simulate fills or PnL.
    """
    from collections import Counter
    counts=Counter()
    gates=Counter()
    variants={n:Counter() for n in (12,16,20,24,32,48,72)}
    samples=0
    for end in range(100, len(completed)+1):
        window=completed[end-100:end]
        prices=[x["c"] for x in window]
        price=prices[-1]
        rsi=calculate_rsi(prices)
        ema20=calculate_ema(prices,20)
        ema50=calculate_ema(prices,50)
        support,resistance=support_resistance(prices)
        avg_prev20=sum(x["v"] for x in window[-21:-1])/20
        volume_ratio=window[-1]["v"]/avg_prev20 if avg_prev20 else None
        momentum_6h=price/prices[-7]-1 if prices[-7] else None
        sig=generate_signal(rsi=rsi,ema20=ema20,ema50=ema50,price=price,
                            support=support,resistance=resistance,
                            volume_ratio=volume_ratio,momentum_6h=momentum_6h)
        counts[sig["signal"]]+=1
        for lookback, bucket in variants.items():
            candidate_support=min(prices[-lookback:])
            candidate=generate_signal(rsi=rsi,ema20=ema20,ema50=ema50,price=price,
                                      support=candidate_support,resistance=resistance,
                                      volume_ratio=volume_ratio,momentum_6h=momentum_6h)
            bucket[candidate["signal"]]+=1
            if candidate["signal"] in ("BUY SETUP","STRONG BUY") and volume_ratio is not None and volume_ratio>VOLUME_THRESHOLD:
                bucket["locked_entry"]+=1
        distance=((price-support)/price)*100 if price else 999
        if ema20>ema50: gates["bullish_trend"]+=1
        if price>=support and distance<=1.5: gates["within_1_5pct_of_100h_support"]+=1
        if support<=price<=round(support*1.005,8): gates["inside_0_5pct_entry_zone"]+=1
        if rsi<65: gates["rsi_below_65"]+=1
        if sig.get("risk_reward") is not None and sig["risk_reward"]>=1.0: gates["risk_reward_at_least_1"]+=1
        if sig["quality_score"]>=65: gates["quality_at_least_65"]+=1
        if volume_ratio is not None and volume_ratio>=1.2: gates["volume_at_least_1_2"]+=1
        if momentum_6h is None or momentum_6h>=-0.01: gates["momentum_gate_pass"]+=1
        if sig["signal"] in ("BUY SETUP","STRONG BUY") and volume_ratio is not None and volume_ratio>VOLUME_THRESHOLD:
            counts["locked_entry"]+=1
        if volume_ratio is not None and volume_ratio>VOLUME_THRESHOLD: counts["volume_gt_1_5"]+=1
        samples+=1
    return {"rolling_windows":samples,"signal_counts":dict(counts),
            "gate_counts":dict(gates),
            "support_lookback_variants":{str(n):dict(v) for n,v in variants.items()},
            "method":"Production rules compared with candidate support lookbacks of 12/16/20/24/32/48/72 completed candles; resistance remains the 100-candle high",
            "note":"Signal-frequency diagnostics only; no simulated trade returns or evidence of profitability."}

def backtest_support_lookback(completed, lookback, horizon=24):
    """Research-only, non-overlapping long-only paper test with conservative intrabar exits."""
    trades=[]
    next_available=100
    last_entry_index=len(completed)-horizon-1
    i=next_available
    while i<=last_entry_index:
        window=completed[i-99:i+1]
        prices=[x["c"] for x in window]
        price=prices[-1]
        rsi=calculate_rsi(prices)
        ema20=calculate_ema(prices,20)
        ema50=calculate_ema(prices,50)
        support=min(prices[-lookback:])
        resistance=max(prices)
        avg_prev20=sum(x["v"] for x in window[-21:-1])/20
        volume_ratio=window[-1]["v"]/avg_prev20 if avg_prev20 else None
        momentum_6h=price/prices[-7]-1 if prices[-7] else None
        sig=generate_signal(rsi=rsi,ema20=ema20,ema50=ema50,price=price,
                            support=support,resistance=resistance,
                            volume_ratio=volume_ratio,momentum_6h=momentum_6h)
        if sig["signal"] not in ("BUY SETUP","STRONG BUY") or volume_ratio is None or volume_ratio<=VOLUME_THRESHOLD:
            i+=1
            continue
        stop=support*0.99
        target=resistance
        exit_price=None
        exit_reason="TIME"
        exit_i=i+horizon
        for k in range(i+1,i+horizon+1):
            bar=completed[k]
            stop_hit=bar["l"]<=stop
            target_hit=bar["h"]>=target
            if stop_hit and target_hit:
                exit_price=stop
                exit_reason="STOP_AND_TARGET_SAME_CANDLE_STOP_FIRST"
                exit_i=k
                break
            if stop_hit:
                exit_price=stop
                exit_reason="STOP"
                exit_i=k
                break
            if target_hit:
                exit_price=target
                exit_reason="TARGET"
                exit_i=k
                break
        if exit_price is None:
            exit_price=completed[exit_i]["c"]
        gross=(exit_price/price-1)*100
        net=round(gross-2*(FEE+SLIPPAGE)*100,4)
        trades.append({
            "entry_time_utc":datetime.fromtimestamp((window[-1]["t"]+3600000)/1000,timezone.utc).isoformat(),
            "exit_time_utc":datetime.fromtimestamp((completed[exit_i]["t"]+3600000)/1000,timezone.utc).isoformat(),
            "entry_price":price,"exit_price":exit_price,"stop":round(stop,8),
            "target":round(target,8),"exit_reason":exit_reason,"gross_return_pct":round(gross,4),
            "net_return_pct":net
        })
        i=exit_i+1
    returns=[t["net_return_pct"] for t in trades]
    wins=[x for x in returns if x>0]
    losses=[-x for x in returns if x<0]
    equity=1.0
    peak=1.0
    max_dd=0.0
    for ret in returns:
        equity*=1+ret/100
        peak=max(peak,equity)
        if peak:
            max_dd=max(max_dd,(peak-equity)/peak*100)
    return {
        "support_lookback":lookback,"horizon_hours":horizon,"trade_count":len(trades),
        "wins":len(wins),"losses":len(losses),"breakeven":len(returns)-len(wins)-len(losses),
        "win_rate_pct":round(100*len(wins)/len(returns),2) if returns else None,
        "average_net_return_pct":round(sum(returns)/len(returns),4) if returns else None,
        "profit_factor":round(sum(wins)/sum(losses),3) if losses else (None if not wins else "infinite_no_losses"),
        "compounded_net_return_pct":round((equity-1)*100,3),
        "max_drawdown_pct":round(max_dd,3),"trades":trades,
        "cost_assumption":"round-trip fee + slippage = 2 * (0.10% + 0.05%)",
        "same_candle_stop_target_rule":"assume stop loss first"
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
    data["historical_signal_diagnostics"]=historical_signal_diagnostics(completed)
    data["candidate_backtests"]={str(n):backtest_support_lookback(completed,n) for n in (12,16,20,24,32,48,72)}
    data["summary"]=metrics(obs)
    with open(LOG_FILE,"w",encoding="utf-8") as f:json.dump(data,f,indent=2)
    print(json.dumps({"latest_signal_utc":data["latest_signal_utc"],
                      "latest_signal":obs[-1]["signal"] if obs else None,
                      "latest_locked_entry":obs[-1]["locked_entry"] if obs else None,
                      "latest_volume_ratio":obs[-1]["volume_ratio"] if obs else None,
                      "summary":data["summary"],"historical_signal_diagnostics":data["historical_signal_diagnostics"],"candidate_backtests":{k:{kk:vv for kk,vv in v.items() if kk!="trades"} for k,v in data["candidate_backtests"].items()},"production_changed":False},indent=2))

if __name__=="__main__": main()
