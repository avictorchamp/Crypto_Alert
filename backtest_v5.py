#!/usr/bin/env python3
"""Crypto Alert V5 Edge Discovery. Research only."""
from __future__ import annotations
import argparse,json,time
from dataclasses import dataclass
from datetime import datetime,timedelta,timezone
from urllib.request import Request,urlopen
PRODUCTS=["BTC-USD","ETH-USD","XRP-USD","SOL-USD","BNB-USD","ADA-USD","DOGE-USD","LINK-USD","AVAX-USD"]
API="https://api.exchange.coinbase.com/products/{}/candles?granularity=3600&start={}&end={}"
FEE=.001;SLIP=.0005;MIN_TRADES=30
@dataclass
class Bar: ts:int; low:float; high:float; close:float
def fetch(product,start,end):
 out=[];cur=start
 while cur<end:
  nxt=min(cur+timedelta(hours=299),end);req=Request(API.format(product,int(cur.timestamp()),int(nxt.timestamp())),headers={"User-Agent":"CryptoAlert-V5"})
  with urlopen(req,timeout=30) as r:data=json.loads(r.read().decode())
  out += [Bar(int(x[0]),float(x[1]),float(x[2]),float(x[4])) for x in data if len(x)>=5];cur=nxt+timedelta(hours=1);time.sleep(.05)
 d={x.ts:x for x in out};return [d[k] for k in sorted(d)]
def ema(v,p):
 k=2/(p+1);x=v[0]
 for z in v[1:]:x=z*k+x*(1-k)
 return x
def rsi(v,p=14):
 if len(v)<=p:return 50
 g=sum(max(b-a,0) for a,b in zip(v[-p-1:-1],v[-p:]));l=sum(max(a-b,0) for a,b in zip(v[-p-1:-1],v[-p:]));return 100 if l==0 else 100-100/(1+g/l)
def feat(b,i):
 if i<50:return None
 c=[x.close for x in b[i-50:i+1]];p=c[-1];e20=ema(c[-20:],20);e50=ema(c,50);rv=rsi(c);sup=min(c[-20:]);res=max(c[-20:]);avg=sum(c[-20:])/20;atr=sum(abs(c[j]-c[j-1]) for j in range(len(c)-14,len(c)))/14
 return p,e20,e50,rv,sup,res,avg,atr
def setups(f,pv):
 p,e20,e50,rv,sup,res,avg,atr=f;bull=e20>e50
 return {"trend_pullback":bull and .97*e20<=p<=1.01*e20,"ema_reclaim":pv and pv[0]<pv[1] and p>=e20 and bull,"breakout":p>res*.995 and bull,"rsi_reversal":30<=rv<=45 and pv and rv>pv[3] and p>pv[0],"support_bounce":p<=sup*1.02 and pv and p>pv[0],"momentum":p>avg*1.01 and bull and atr/p>.002}
def measure(b,i):
 if i+25>=len(b):return None
 e=b[i+1].close*(1+SLIP);f=b[i+1:i+25];ret=f[-1].close*(1-SLIP)/e-1;best=max(x.high*(1-SLIP)/e-1 for x in f);worst=min(x.low*(1-SLIP)/e-1 for x in f);return ret,best,worst
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--months',type=int,default=12);a=ap.parse_args();end=datetime.now(timezone.utc);start=end-timedelta(days=30.44*a.months);rows=[]
 for coin in PRODUCTS:
  try:b=fetch(coin,start,end)
  except Exception as e:rows.append({'coin':coin,'error':str(e)});continue
  for i in range(51,len(b)-25):
   f=feat(b,i);pv=feat(b,i-1)
   for s,on in setups(f,pv).items():
    if on:
     m=measure(b,i)
     if m:rows.append({'coin':coin,'setup':s,'regime':'BULL' if f[1]>f[2] else 'BEAR','ret':m[0],'best':m[1],'worst':m[2]})
 groups={}
 for r in rows:
  if 'setup' in r:groups.setdefault((r['coin'],r['setup'],r['regime']),[]).append(r)
 out=[]
 for (coin,s,reg),g in groups.items():
  v=[x['ret'] for x in g];w=sum(x for x in v if x>0);l=-sum(x for x in v if x<0);pf=w/l if l else None;ex=sum(v)/len(v);n=len(v)
  out.append({'coin':coin,'setup':s,'regime':reg,'trades':n,'win_rate_pct':round(100*sum(x>0 for x in v)/n,2),'expectancy_pct':round(ex*100,4),'profit_factor':round(pf,3) if pf else None,'avg_best_pct':round(100*sum(x['best'] for x in g)/n,3),'avg_worst_pct':round(100*sum(x['worst'] for x in g)/n,3),'candidate':n>=MIN_TRADES and pf is not None and pf>1 and ex>0})
 out.sort(key=lambda x:(not x['candidate'],-(x['profit_factor'] or -999),-x['trades']));payload={'version':'5.0.1','purpose':'EDGE_DISCOVERY','months':a.months,'horizon_hours':24,'min_trades_for_candidate':MIN_TRADES,'costs':{'fee_per_side':FEE,'slippage_per_side':SLIP},'groups':out};open('backtest_v5_results.json','w').write(json.dumps(payload,indent=2));print(json.dumps(payload,indent=2))
if __name__=='__main__':main()
