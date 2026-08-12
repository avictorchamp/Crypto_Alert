#!/usr/bin/env python3
"""Crypto Alert Backtest V4.0.0 - behavior-based strategy research.

Research only. Public Coinbase 1H candles. No account access and no trading.
V4 groups each coin dynamically from historical behavior at each decision point:
TREND, MOMENTUM, or RANGE. Rules are intentionally small and fixed to reduce
per-coin overfitting. Results include full-period and out-of-sample holdout.
"""
from __future__ import annotations
import argparse, json, math, statistics, time
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
import requests

BASE="https://api.exchange.coinbase.com/products/{}/candles"
COINS=["BTC","ETH","XRP","SOL","BNB","ADA","DOGE","LINK","AVAX"]
FEE=0.001; SLIP=0.0005; INITIAL=10000.0; RISK=0.01; MAX_HOLD=72

@dataclass
class Trade:
    coin:str; group:str; entry_ts:int; exit_ts:int; r:float; pnl_pct:float; reason:str

def fetch(coin, months):
    end=datetime.now(timezone.utc); start=end-timedelta(days=months*30.4375); cur=start; out=[]; s=requests.Session()
    while cur<end:
        nxt=min(cur+timedelta(hours=299),end)
        p={"start":cur.isoformat().replace('+00:00','Z'),"end":nxt.isoformat().replace('+00:00','Z'),"granularity":3600}
        r=s.get(BASE.format(f"{coin}-USD"),params=p,timeout=30); r.raise_for_status(); batch=r.json(); out+=batch
        cur=nxt+timedelta(hours=1); time.sleep(.08)
    d={int(x[0]):x for x in out}; return [{"ts":k,"open":float(v[3]),"high":float(v[2]),"low":float(v[1]),"close":float(v[4]),"vol":float(v[5])} for k,v in sorted(d.items())]

def ema(v,n):
    if len(v)<n:return None
    k=2/(n+1); x=v[0]
    for z in v[1:]: x=z*k+x*(1-k)
    return x

def rsi(v,n=14):
    if len(v)<=n:return 50
    g=[max(v[i]-v[i-1],0) for i in range(1,len(v))][-n:]; l=[max(v[i-1]-v[i],0) for i in range(1,len(v))][-n:]
    ag=sum(g)/n; al=sum(l)/n
    return 100 if al==0 else 100-100/(1+ag/al)

def behavior(h):
    c=[x['close'] for x in h]; v=[x['vol'] for x in h]
    e20=ema(c[-60:],20); e50=ema(c[-60:],50); p=c[-1]
    atr=statistics.mean([x['high']-x['low'] for x in h[-14:]])/p
    # Trend persistence: fraction of last 20 closes moving in same direction.
    d=[1 if c[i]>c[i-1] else -1 if c[i]<c[i-1] else 0 for i in range(len(c)-20,len(c))]
    persistence=max(sum(x==1 for x in d),sum(x==-1 for x in d))/20
    vol_ratio=(statistics.mean(v[-5:])/(statistics.mean(v[-30:]) or 1))
    if e20 and e50 and abs(e20-e50)/p>=0.012 and persistence>=0.60:
        return 'TREND',e20,e50,atr,vol_ratio
    if atr>=0.025 or vol_ratio>=1.6:
        return 'MOMENTUM',e20,e50,atr,vol_ratio
    return 'RANGE',e20,e50,atr,vol_ratio

def signal(h):
    if len(h)<60:return None
    c=[x['close'] for x in h]; p=c[-1]; e20=ema(c[-60:],20); e50=ema(c[-60:],50); rv=rsi(c)
    group,e20,e50,atr,vr=behavior(h); lo=min(c[-30:]); hi=max(c[-30:]); prev=c[-2]
    # Fixed group rules; no coin-specific tuning.
    if group=='TREND':
        # Pullback in an established trend, then reclaim previous close.
        ok=e20>e50 and p<=e20*1.01 and p>prev and rv>=45 and rv<=68
        stop=p-max(atr*1.5,p*0.008); target=p+(p-stop)*1.8
    elif group=='MOMENTUM':
        ok=p>hi*0.995 and p>prev and rv>=55 and vr>=1.15
        stop=p-max(atr*1.8,p*0.012); target=p+(p-stop)*2.0
    else:
        # Mean reversion only near the lower part of the range.
        ok=p<=lo*1.02 and rv<=38 and p>prev
        stop=p-max(atr*1.2,p*0.008); target=min(hi,p+(p-stop)*1.6)
    risk=p-stop; rr=(target-p)/risk if risk>0 else 0
    if ok and risk>0 and rr>=1.5:return group,p,stop,target,rr
    return None

def simulate(bars,coin,start_i=60,end_i=None):
    end_i=end_i or len(bars)-2; trades=[]; i=start_i
    while i<end_i:
        s=signal(bars[:i+1])
        if not s:i+=1;continue
        group,p,stop,target,rr=s; entry_i=i+1; entry=bars[entry_i]['open']*(1+SLIP); risk=entry-stop
        if risk<=0:i+=1;continue
        exit_i=min(entry_i+MAX_HOLD,end_i+1); reason='TIME'; px=bars[exit_i]['close']*(1-SLIP)
        for j in range(entry_i,exit_i+1):
            b=bars[j]
            if b['low']<=stop: px=stop*(1-SLIP);exit_i=j;reason='SL';break
            if b['high']>=target: px=target*(1-SLIP);exit_i=j;reason='TP';break
        net=(px-entry)/entry-2*FEE; r=(px-entry)/risk
        trades.append(Trade(coin,group,bars[entry_i]['ts'],bars[exit_i]['ts'],r,net*100,reason)); i=exit_i+1
    return trades

def metrics(ts):
    if not ts:return {'trades':0,'win_rate_pct':0,'profit_factor':0,'expectancy_pct':0,'avg_R':0,'max_drawdown_pct':0,'net_return_pct':0}
    wins=sum(t.pnl_pct>0 for t in ts); gw=sum(t.pnl_pct for t in ts if t.pnl_pct>0); gl=-sum(t.pnl_pct for t in ts if t.pnl_pct<=0)
    pf=gw/gl if gl else float('inf'); eq=INITIAL; peak=eq; dd=0
    for t in ts:
        eq*=1+RISK*t.r; peak=max(peak,eq); dd=max(dd,(peak-eq)/peak*100)
    return {'trades':len(ts),'win_rate_pct':round(wins/len(ts)*100,2),'profit_factor':round(pf,3) if math.isfinite(pf) else 'INF','expectancy_pct':round(statistics.mean(t.pnl_pct for t in ts),4),'avg_R':round(statistics.mean(t.r for t in ts),4),'max_drawdown_pct':round(dd,2),'net_return_pct':round((eq/INITIAL-1)*100,2)}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--months',type=int,default=12);ap.add_argument('--coins',nargs='+',default=COINS);a=ap.parse_args()
    allv=[]; by_coin={}; wf=[]
    for coin in a.coins:
        try:b=fetch(coin.upper(),a.months)
        except Exception as e:by_coin[coin]={'error':str(e)};continue
        cut=int(len(b)*0.6); ts=simulate(b,coin.upper()); test=simulate(b,coin.upper(),start_i=max(60,cut),end_i=len(b)-2)
        by_coin[coin.upper()]={'full':metrics(ts),'walk_forward':metrics(test),'groups':{g:metrics([t for t in ts if t.group==g]) for g in ('TREND','MOMENTUM','RANGE')}};allv+=ts;wf+=test
    result={'version':'4.0.0','months':a.months,'costs':{'fee_per_side':FEE,'slippage_per_side':SLIP},'risk_per_trade':RISK,'strategy':'behavior_based_fixed_rules','full_period':metrics(allv),'walk_forward':metrics(wf),'by_coin':by_coin,'decision_rule':'Do not deploy unless PF>1, expectancy>0, walk-forward positive, and edge is not concentrated in a tiny sample.'}
    print(json.dumps(result,indent=2));open('backtest_v4_results.json','w',encoding='utf-8').write(json.dumps(result,indent=2))
if __name__=='__main__':main()
