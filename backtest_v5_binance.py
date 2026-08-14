#!/usr/bin/env python3
"""Crypto Alert V5 Binance Edge Discovery. Research only; never trades."""
from __future__ import annotations
import argparse,json,time
from datetime import datetime,timedelta,timezone
from urllib.request import Request,urlopen
SYMBOLS=['BTCUSDT','ETHUSDT','XRPUSDT','SOLUSDT','BNBUSDT','ADAUSDT','DOGEUSDT','LINKUSDT','AVAXUSDT']
BASE='https://api.binance.com/api/v3/klines';FEE=.001;SLIP=.0005;MIN_TRADES=30

def fetch(symbol,start,end):
 out=[];cur=int(start.timestamp()*1000);endms=int(end.timestamp()*1000)
 while cur<endms:
  url=f'{BASE}?symbol={symbol}&interval=1h&startTime={cur}&endTime={endms}&limit=1000'
  with urlopen(Request(url,headers={'User-Agent':'CryptoAlert-V5'}),timeout=30) as r:data=json.loads(r.read().decode())
  if not data:break
  out+=data;n=int(data[-1][0])
  if n<=cur:break
  cur=n+3600000;time.sleep(.05)
 d={int(x[0]):x for x in out};return [{'ts':k,'open':float(v[1]),'high':float(v[2]),'low':float(v[3]),'close':float(v[4]),'volume':float(v[5])} for k,v in sorted(d.items())]

def ema(v,p):
 k=2/(p+1);x=v[0]
 for z in v[1:]:x=z*k+x*(1-k)
 return x

def rsi(v,p=14):
 if len(v)<=p:return 50
 g=sum(max(b-a,0) for a,b in zip(v[-p-1:-1],v[-p:]));l=sum(max(a-b,0) for a,b in zip(v[-p-1:-1],v[-p:]));return 100 if l==0 else 100-100/(1+g/l)

def feat(b,i):
 if i<50:return None
 c=[x['close'] for x in b[i-50:i+1]];vol=[x['volume'] for x in b[i-20:i+1]];p=c[-1];e20=ema(c[-20:],20);e50=ema(c,50);rv=rsi(c);sup=min(c[-20:]);res=max(c[-20:]);avg=sum(c[-20:])/20;atr=sum(abs(c[j]-c[j-1]) for j in range(len(c)-14,len(c)))/14;va=sum(vol[:-1])/20
 return p,e20,e50,rv,sup,res,avg,atr,b[i]['volume'],va

def setups(f,pv):
 p,e20,e50,rv,sup,res,avg,atr,vol,va=f;bull=e20>e50
 return {'trend_pullback':bull and .97*e20<=p<=1.01*e20,'ema_reclaim':pv and pv[0]<pv[1] and p>=e20 and bull,'breakout':p>=res and bull and vol>=1.2*va,'rsi_reversal':30<=rv<=45 and pv and rv>pv[3] and p>pv[0],'support_bounce':p<=sup*1.02 and pv and p>pv[0],'momentum':p>avg*1.01 and bull and vol>=1.5*va}

def outcome(b,i,h=24):
 if i+1+h>len(b):return None
 entry=b[i+1]['open']*(1+SLIP);f=b[i+1:i+1+h];return (f[-1]['close']*(1-SLIP)/entry-1,max(x['high']*(1-SLIP)/entry-1 for x in f),min(x['low']*(1-SLIP)/entry-1 for x in f))

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--months',type=int,default=12);a=ap.parse_args();end=datetime.now(timezone.utc);start=end-timedelta(days=30.44*a.months);rows=[]
 for coin in SYMBOLS:
  try:b=fetch(coin,start,end)
  except Exception as e:rows.append({'coin':coin,'error':str(e)});continue
  for i in range(51,len(b)-25):
   f=feat(b,i);pv=feat(b,i-1)
   for s,on in setups(f,pv).items():
    if on:
     o=outcome(b,i)
     if o:rows.append({'coin':coin,'setup':s,'regime':'BULL' if f[1]>f[2] else 'BEAR','ret':o[0],'best':o[1],'worst':o[2]})
 groups={}
 for r in rows:
  if 'setup' in r:groups.setdefault((r['coin'],r['setup'],r['regime']),[]).append(r)
 result=[]
 for (coin,s,reg),g in groups.items():
  v=[x['ret'] for x in g];n=len(v);wins=sum(x>0 for x in v);loss=-sum(x for x in v if x<0);pf=sum(x for x in v if x>0)/loss if loss else None;ex=sum(v)/n
  result.append({'coin':coin,'setup':s,'regime':reg,'trades':n,'win_rate_pct':round(100*wins/n,2),'expectancy_pct':round(ex*100,4),'profit_factor':round(pf,3) if pf is not None else None,'avg_best_pct':round(100*sum(x['best'] for x in g)/n,3),'avg_worst_pct':round(100*sum(x['worst'] for x in g)/n,3),'candidate':bool(n>=MIN_TRADES and pf is not None and pf>1 and ex>0)})
 result.sort(key=lambda x:(not x['candidate'],-(x['profit_factor'] or -999),-x['trades']));payload={'version':'5.2.0','source':'BINANCE_SPOT','purpose':'EDGE_DISCOVERY','months':a.months,'interval':'1h','horizon_hours':24,'min_trades_for_candidate':MIN_TRADES,'costs':{'fee_per_side':FEE,'slippage_per_side':SLIP},'groups':result,'errors':[x for x in rows if 'error' in x]};open('backtest_v5_binance_results.json','w').write(json.dumps(payload,indent=2));print(json.dumps(payload,indent=2))
if __name__=='__main__':main()
