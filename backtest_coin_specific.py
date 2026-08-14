#!/usr/bin/env python3
"""Research backtest: coin-specific rules using Binance public klines with fallback endpoints. Never trades."""
from __future__ import annotations
import argparse,json,time
from datetime import datetime,timedelta,timezone
from urllib.request import Request,urlopen
SYMBOLS=['BTCUSDT','ETHUSDT','XRPUSDT','SOLUSDT','BNBUSDT','ADAUSDT','DOGEUSDT','LINKUSDT','AVAXUSDT']
BASES=['https://api.binance.com/api/v3/klines','https://api1.binance.com/api/v3/klines','https://api2.binance.com/api/v3/klines','https://api3.binance.com/api/v3/klines']
FEE=.001;SLIP=.0005

def fetch(s,a,b):
 last=None
 for base in BASES:
  try:
   out=[];cur=int(a.timestamp()*1000);end=int(b.timestamp()*1000)
   while cur<end:
    u=f'{base}?symbol={s}&interval=1h&startTime={cur}&endTime={end}&limit=1000'
    with urlopen(Request(u,headers={'User-Agent':'Mozilla/5.0'}),timeout=30) as r:d=json.loads(r.read().decode())
    if not d: break
    out+=d;n=int(d[-1][0])
    if n<=cur:break
    cur=n+3600000;time.sleep(.05)
   if len(out)>100:return [{'o':float(x[1]),'h':float(x[2]),'l':float(x[3]),'c':float(x[4]),'v':float(x[5])} for x in out]
  except Exception as e:last=e
 raise last or RuntimeError('No Binance data')

def ema(v,p):
 k=2/(p+1);x=v[0]
 for z in v[1:]:x=z*k+x*(1-k)
 return x

def rsi(v,p=14):
 g=sum(max(b-a,0) for a,b in zip(v[-p-1:-1],v[-p:]));l=sum(max(a-b,0) for a,b in zip(v[-p-1:-1],v[-p:]));return 50 if g+l==0 else 100 if l==0 else 100-100/(1+g/l)

def feat(b,i):
 c=[x['c'] for x in b[i-50:i+1]];p=c[-1];e20=ema(c[-20:],20);e50=ema(c,50);rr=rsi(c);sup=min(c[-20:]);res=max(c[-20:]);avg=sum(c[-20:])/20;va=sum(x['v'] for x in b[i-20:i])/20
 return p,e20,e50,rr,sup,res,avg,b[i]['v'],va

def signals(x):
 p,e20,e50,rr,sup,res,avg,vol,va=x;bull=e20>e50;near=(p-sup)/p<=.015;entry=sup<=p<=sup*1.005;mid=(sup+sup*1.005)/2;rratio=(res-mid)/(mid-sup*.99) if sup>0 else 0
 quality=(25 if bull else 0)+(20 if 40<=rr<=55 else 18 if rr<35 else 15 if rr<=65 else 5)+(20 if near else 10 if (p-sup)/p<=.03 else 0)+(15 if entry else 5 if p<=sup*1.01 else 0)+(20 if rratio>=2 else 15 if rratio>=1.5 else 10 if rratio>=1 else 0)
 return {'baseline':bull and near and rr<65 and rratio>=1 and quality>=65 and entry,'trend_pullback':bull and .97*e20<=p<=1.01*e20 and rr<65 and rratio>=1,'support_rsi':near and rr<45 and entry and rratio>=1,'reclaim':bull and p>=e20 and p<=e20*1.01 and rr<60 and rratio>=1,'momentum':bull and p>avg*1.01 and vol>=1.5*va and rratio>=1}

def outcome(b,i,h=24):
 if i+1+h>=len(b):return None
 entry=b[i+1]['o']*(1+SLIP);z=b[i+1:i+1+h];return z[-1]['c']*(1-SLIP)/entry-1,max(q['h']*(1-SLIP)/entry-1 for q in z),min(q['l']*(1-SLIP)/entry-1 for q in z)

def stats(rows):
 if not rows:return None
 r=[x[0] for x in rows];w=[x for x in r if x>0];loss=-sum(x for x in r if x<0);pf=sum(w)/loss if loss else None
 return {'trades':len(r),'win_rate_pct':round(100*len(w)/len(r),2),'expectancy_pct':round(100*sum(r)/len(r),4),'profit_factor':round(pf,3) if pf is not None else None,'avg_best_pct':round(100*sum(x[1] for x in rows)/len(rows),3),'avg_worst_pct':round(100*sum(x[2] for x in rows)/len(rows),3)}

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--months',type=int,default=24);a=ap.parse_args();end=datetime.now(timezone.utc);start=end-timedelta(days=30.44*a.months);allres={}
 for coin in SYMBOLS:
  try:b=fetch(coin,start,end)
  except Exception as e:allres[coin]={'error':str(e)};continue
  cut=int(len(b)*.67);train={};test={}
  for i in range(51,len(b)-25):
   sg=signals(feat(b,i));o=outcome(b,i)
   if not o:continue
   target=train if i<cut else test
   for name,on in sg.items():
    if on:target.setdefault(name,[]).append(o)
  candidates=[]
  for name,rows in train.items():
   st=stats(rows)
   if st and st['trades']>=30 and (st['profit_factor'] or 0)>1 and st['expectancy_pct']>0:candidates.append((name,st))
  candidates.sort(key=lambda z:(z[1]['expectancy_pct'],z[1]['profit_factor'] or 0),reverse=True);selected=candidates[0][0] if candidates else 'baseline'
  allres[coin]={'train':{k:stats(v) for k,v in train.items()},'test':{k:stats(v) for k,v in test.items()},'selected_rule':selected,'selected_train':stats(train.get(selected,[])),'selected_test':stats(test.get(selected,[]))}
 payload={'version':'6.0.2','purpose':'COIN_SPECIFIC_RESEARCH','source':'BINANCE_SPOT','months':a.months,'interval':'1h','train_fraction':.67,'test_fraction':.33,'horizon_hours':24,'costs':{'fee_per_side':FEE,'slippage_per_side':SLIP},'selection_rule':'TRAIN only: >=30 trades, PF>1, expectancy>0; unchanged TEST','results':allres}
 open('backtest_coin_specific_results.json','w').write(json.dumps(payload,indent=2));print(json.dumps(payload,indent=2))
if __name__=='__main__':main()
