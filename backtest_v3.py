#!/usr/bin/env python3
"""Crypto Alert Backtest V3.0.0 - research only.

Tests the existing CURRENT entry logic against V3 adaptive-exit confirmation.
No exchange account access and no trading. Uses Coinbase public 1H candles.
"""
from __future__ import annotations
import argparse, json, math, statistics, time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
import requests

BASE='https://api.exchange.coinbase.com/products/{}/candles'
COINS=['BTC','ETH','XRP','SOL','BNB','ADA','DOGE','LINK','AVAX']
FEE=0.001; SLIP=0.0005; RISK=0.01; INITIAL=10000.0; MAX_HOLD=72; MAX_POS=3

@dataclass
class Trade:
    coin:str; strategy:str; entry_time:int; exit_time:int; entry:float; exit:float
    stop:float; target:float; r:float; pnl_pct:float; reason:str; bars:int

def candles(coin,months):
    end=datetime.now(timezone.utc); start=end-timedelta(days=30.4375*months); cur=start; out=[]
    s=requests.Session(); s.headers['User-Agent']='Crypto-Alert-Backtest/3.0'
    while cur<end:
        nxt=min(cur+timedelta(hours=299),end)
        p={'start':cur.isoformat().replace('+00:00','Z'),'end':nxt.isoformat().replace('+00:00','Z'),'granularity':3600}
        r=s.get(BASE.format(f'{coin}-USD'),params=p,timeout=30); r.raise_for_status()
        out.extend(r.json()); cur=nxt+timedelta(hours=1); time.sleep(.08)
    d={int(x[0]):x for x in out}; return [dict(t=int(k),o=float(v[3]),h=float(v[2]),l=float(v[1]),c=float(v[4])) for k,v in sorted(d.items())]

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

def ind(h):
    if len(h)<50:return None
    c=[x['c'] for x in h]; p=c[-1]; e20=ema(c,20); e50=ema(c,50); sup=min(c[-50:]); res=max(c[-50:]); rr=(res-p)/(p-sup) if p>sup else 0
    return {'p':p,'e20':e20,'e50':e50,'rsi':rsi(c),'sup':sup,'res':res,'rr':rr,'entry_hi':sup*1.005,'stop':sup*.99}

def current(h):
    x=ind(h)
    if not x:return False,x
    q=(25 if x['e20']>x['e50'] else 0)+(20 if x['p']<=x['sup']*1.01 else 0)+(15 if x['rsi']<65 else 0)+(20 if x['rr']>=1 else 0)+(20 if x['p']<=x['entry_hi'] else 0)
    return x['e20']>x['e50'] and x['p']<=x['sup']*1.01 and x['rsi']<65 and x['rr']>=1 and q>=70 and x['p']<=x['entry_hi'],x

def v3(h):
    x=ind(h); p1=ind(h[:-1]) if len(h)>50 else None; p2=ind(h[:-2]) if len(h)>51 else None
    if not x or not p1 or not p2:return False,x
    c=[z['c'] for z in h]; q=(25 if x['e20']>x['e50'] else 0)+(20 if x['p']<=x['sup']*1.01 else 0)+(15 if x['rsi']<65 else 0)+(20 if x['rr']>=1 else 0)+(20 if x['p']<=x['entry_hi'] else 0)
    recovery=x['rsi']>p1['rsi'] and (p1['rsi']<=35 or p2['rsi']<=35)
    two_up=c[-1]>c[-2]>c[-3] and x['rsi']>p1['rsi']
    return x['e20']>x['e50'] and x['p']<=x['sup']*1.01 and x['p']<=x['entry_hi'] and x['rr']>=1.5 and q>=70 and x['p']>p1['p'] and (recovery or two_up),x

def make_trade(bs,i,coin,strategy,x):
    e=bs[i+1]['o']*(1+SLIP); stop=x['stop']; risk=e-stop
    if risk<=0:return None
    # Adaptive exit: initial 1.5R target; once +1R is reached, stop moves to BE.
    target=e+1.5*risk; be=False; end=min(len(bs)-1,i+1+MAX_HOLD)
    for j in range(i+1,end+1):
        b=bs[j]
        if b['h']>=e+risk: be=True
        active_stop=e if be else stop
        if b['l']<=active_stop:return Trade(coin,strategy,bs[i+1]['t'],b['t'],e,active_stop*(1-SLIP),stop,target,(active_stop-e)/risk-2*FEE*e/risk,((active_stop-e)/e-2*FEE)*100,'BE' if be else 'SL',j-i-1),j
        if b['h']>=target:return Trade(coin,strategy,bs[i+1]['t'],b['t'],e,target*(1-SLIP),stop,target,(target-e)/risk-2*FEE*e/risk,((target-e)/e-2*FEE)*100,'TP',j-i-1),j
    px=bs[end]['c']*(1-SLIP); return Trade(coin,strategy,bs[i+1]['t'],bs[end]['t'],e,px,stop,target,(px-e)/risk-2*FEE*e/risk,((px-e)/e-2*FEE)*100,'TIME',end-i-1),end

def run_coin(bs,coin,strategy,cut=None):
    end=len(bs) if cut is None else cut; ts=[]; i=50
    while i<end-2:
        h=bs[:i+1]; ok,x=current(h) if strategy=='CURRENT' else v3(h)
        if ok:
            z=make_trade(bs,i,coin,strategy,x)
            if z and z[1]<end: ts.append(z[0]); i=z[1]+1; continue
        i+=1
    return ts

def metrics(ts):
    if not ts:return {'trades':0,'win_rate_pct':0,'profit_factor':0,'expectancy_pct':0,'avg_R':0,'max_drawdown_pct':0,'net_return_pct':0}
    wins=[t for t in ts if t.pnl_pct>0]; losses=[t for t in ts if t.pnl_pct<=0]; gw=sum(t.pnl_pct for t in wins); gl=abs(sum(t.pnl_pct for t in losses)); eq=INITIAL; peak=eq; dd=0
    for t in ts:
        eq*=1+RISK*t.r; peak=max(peak,eq); dd=max(dd,(peak-eq)/peak*100)
    return {'trades':len(ts),'win_rate_pct':round(100*len(wins)/len(ts),2),'profit_factor':round(gw/gl,3) if gl else 'INF','expectancy_pct':round(statistics.mean(t.pnl_pct for t in ts),4),'avg_R':round(statistics.mean(t.r for t in ts),4),'max_drawdown_pct':round(dd,2),'net_return_pct':round((eq/INITIAL-1)*100,2)}

def capacity(ts):
    active=[]; chosen=[]
    for t in sorted(ts,key=lambda x:(x.entry_time,x.coin)):
        active=[a for a in active if a.exit_time>t.entry_time]
        if len(active)<MAX_POS:active.append(t);chosen.append(t)
    return metrics(chosen),len(chosen)

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--months',type=int,default=12); args=ap.parse_args()
    bycoin={}; pool={'CURRENT':[],'V3':[]}; wf={'CURRENT':[],'V3':[]}
    errors=[]
    for coin in COINS:
        try:b=candles(coin,args.months)
        except Exception as e: errors.append({'coin':coin,'error':str(e)}); continue
        bycoin[coin]={}
        cut=int(len(b)*.6)
        for st in ('CURRENT','V3'):
            t=run_coin(b,coin,st); w=run_coin(b,coin,st,cut)
            bycoin[coin][st]=metrics(t); pool[st]+=t; wf[st]+=w
    report={'version':'3.0.0','months':args.months,'costs':{'fee_per_side':FEE,'slippage_per_side':SLIP},'risk_per_trade':RISK,'max_concurrent_positions':MAX_POS,'strategy_summary':{s:metrics(t) for s,t in pool.items()},'portfolio_capacity':{s:capacity(t)[0] for s,t in pool.items()},'walk_forward_test':{s:metrics(t) for s,t in wf.items()},'by_coin':bycoin,'errors':errors}
    print(json.dumps(report,indent=2)); open('backtest_v3_results.json','w',encoding='utf-8').write(json.dumps(report,indent=2)); open('backtest_results.txt','w',encoding='utf-8').write(json.dumps(report,indent=2))
if __name__=='__main__':main()
