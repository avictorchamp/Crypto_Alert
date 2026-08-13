#!/usr/bin/env python3
"""Crypto Alert V5 Edge Discovery.
Research only. Discovers empirical setup expectancy by coin, setup and regime.
It does NOT select or deploy a trading strategy and never touches exchange accounts.
"""
from __future__ import annotations
import argparse, json, math, time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.request import Request, urlopen

PRODUCTS=["BTC-USD","ETH-USD","XRP-USD","SOL-USD","BNB-USD","ADA-USD","DOGE-USD","LINK-USD","AVAX-USD"]
API="https://api.exchange.coinbase.com/products/{}/candles?granularity=3600&start={}&end={}"
FEE=0.001; SLIP=0.0005; MIN_TRADES=30
@dataclass
class Bar: ts:int; low:float; high:float; close:float

def fetch(product,start,end):
    out=[]; cur=start
    while cur<end:
        nxt=min(cur+timedelta(hours=299),end)
        req=Request(API.format(product,int(cur.timestamp()),int(nxt.timestamp())),headers={"User-Agent":"CryptoAlert-EdgeDiscovery/5.0"})
        with urlopen(req,timeout=30) as r: data=json.loads(r.read().decode())
        for x in data:
            if len(x)>=5: out.append(Bar(int(x[0]),float(x[1]),float(x[2]),float(x[4])))
        cur=nxt+timedelta(hours=1); time.sleep(.08)
    return [dict({b.ts:b for b in out})[k] for k in sorted({b.ts for b in out})]

def ema(v,p):
    if not v:return 0
    k=2/(p+1); x=v[0]
    for z in v[1:]:x=z*k+x*(1-k)
    return x

def rsi(v,p=14):
    if len(v)<=p:return 50
    g=l=0
    for a,b in zip(v[-p-1:-1],v[-p:]):
        d=b-a;g+=max(d,0);l+=max(-d,0)
    return 100 if l==0 else 100-100/(1+g/l)

def features(bars,i):
    if i<50:return None
    c=[b.close for b in bars[i-50:i+1]]; p=c[-1]; e20=ema(c[-20:],20); e50=ema(c,50); rr20=max(c[-20:]); sup20=min(c[-20:]); rv=rsi(c)
    avg=sum(c[-20:])/20; atr=sum(abs(c[j]-c[j-1]) for j in range(len(c)-14,len(c)))/14
    return p,e20,e50,rv,sup20,rr20,avg,atr

def setups(f,prev):
    p,e20,e50,rv,sup,res,avg,atr=f
    regime="BULL" if e20>e50 else "BEAR"
    return {
      "trend_pullback": regime=="BULL" and p<=e20*1.01 and p>=e20*0.97,
      "ema_reclaim": prev is not None and prev[0]<prev[1] and p>=e20 and regime=="BULL",
      "breakout": p>res*0.995 and regime=="BULL",
      "rsi_reversal": rv>=30 and rv<=45 and prev is not None and rv>prev[3] and p>prev[0],
      "support_bounce": p<=sup*1.02 and prev is not None and p>prev[0],
      "momentum": p>avg*1.01 and regime=="BULL" and atr/p>0.002,
    }

def measure(bars,i,horizon):
    entry=bars[i+1].close*(1+SLIP); future=bars[i+1:i+1+horizon]
    if not future:return None
    ret=(future[-1].close*(1-SLIP)/entry)-1
    best=max((b.high*(1-SLIP)/entry)-1 for b in future)
    worst=min((b.low*(1-SLIP)/entry)-1 for b in future)
    return ret,best,worst

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--months',type=int,default=12);args=ap.parse_args()
    end=datetime.now(timezone.utc);start=end-timedelta(days=30.44*args.months)
    records=[]
    for product in PRODUCTS:
        try:bars=fetch(product,start,end)
        except Exception as e: records.append({'coin':product,'error':str(e)});continue
        for i in range(51,len(bars)-25):
            f=features(bars,i); prev=features(bars,i-1); ss=setups(f,prev)
            for name,on in ss.items():
                if not on:continue
                m=measure(bars,i,24)
                if m:
                    records.append({'coin':product,'setup':name,'regime':'BULL' if f[1]>f[2] else 'BEAR','ret24':m[0],'best24':m[1],'worst24':m[2]})
    groups={}
    for r in records:
        if 'setup' not in r:continue
        k=(r['coin'],r['setup'],r['regime']);g=groups.setdefault(k,[]);g.append(r)
    result=[]
    for (coin,setup,regime),g in groups.items():
        n=len(g); vals=[x['ret24'] for x in g]; wins=[x for x in vals if x>0]; losses=[x for x in vals if x<0]
        grossw=sum(wins); grossl=-sum(losses); pf=grossw/grossl if grossl else None
        result.append({'coin':coin,'setup':setup,'regime':regime,'trades':n,'win_rate_pct':round(100*len(wins)/n,2),'expectancy_pct':round(100*sum(vals)/n,4),'profit_factor':round(pf,3) if pf is not None else None,'avg_best_pct':round(100*sum(x['best24'] for x in g)/n,3),'avg_worst_pct':round(100*sum(x['worst24'] for x in g)/n,3),'candidate':bool(n>=MIN_TRADES and pf is not None and pf>1 and sum(vals)/n>0)})
    result.sort(key=lambda x:(not x['candidate'],-(x['profit_factor'] or -999),-x['trades']))
    payload={'version':'5.0.0','purpose':'EDGE_DISCOVERY','months':args.months,'horizon_hours':24,'min_trades_for_candidate':MIN_TRADES,'costs':{'fee_per_side':FEE,'slippage_per_side':SLIP},'groups':result}
    print(json.dumps(payload,indent=2));open('backtest_v5_results.json','w',encoding='utf-8').write(json.dumps(payload,indent=2))
if __name__=='__main__':main()
