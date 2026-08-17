#!/usr/bin/env python3
"""V7.1 research backtest: 1H entry vs 1D context + 1H entry.
Research only. Never trades and never changes production.
"""
from __future__ import annotations
import argparse,io,json,time,zipfile
from datetime import datetime,timedelta,timezone
from urllib.request import Request,urlopen
SYMBOLS=['BTCUSDT','ETHUSDT','XRPUSDT','SOLUSDT','BNBUSDT','ADAUSDT','DOGEUSDT','LINKUSDT','AVAXUSDT']
H='https://data.binance.vision/data/spot/monthly/klines/{s}/1h/{s}-1h-{m}.zip'
D='https://data.binance.vision/data/spot/monthly/klines/{s}/1d/{s}-1d-{m}.zip'
FEE=.001;SLIP=.0005;HORIZON=24
RULES=('baseline','trend_pullback','support_rsi','reclaim','momentum')

def months(a,b):
 y,m=a.year,a.month
 while (y,m)<=(b.year,b.month):
  yield f'{y:04d}-{m:02d}';m+=1
  if m==13:y+=1;m=1

def parse_ts(x):
 x=int(x)
 while x>10_000_000_000_000:x//=1000
 return x

def fetch(url,start,end):
 out=[]
 for mo in months(start,end):
  try:
   with urlopen(Request(url.format(m=mo),headers={'User-Agent':'CryptoAlert-Research/7.1'}),timeout=60) as r:data=r.read()
   with zipfile.ZipFile(io.BytesIO(data)) as z:
    with z.open(z.namelist()[0]) as f:
     for raw in f:
      a=raw.decode().strip().split(',')
      if len(a)<6 or not a[0].isdigit():continue
      t=parse_ts(a[0]);dt=datetime.fromtimestamp(t/1000,timezone.utc)
      if start<=dt<=end:out.append({'t':t,'o':float(a[1]),'h':float(a[2]),'l':float(a[3]),'c':float(a[4]),'v':float(a[5])})
  except Exception as e:
   if '404' not in str(e):raise RuntimeError(f'{mo}: {e}')
  time.sleep(.02)
 out.sort(key=lambda x:x['t']);return out

def ema(v,p):
 k=2/(p+1);x=v[0]
 for q in v[1:]:x=q*k+x*(1-k)
 return x

def rsi(v,p=14):
 g=sum(max(b-a,0) for a,b in zip(v[-p-1:-1],v[-p:]));l=sum(max(a-b,0) for a,b in zip(v[-p-1:-1],v[-p:]))
 return 50 if g+l==0 else 100 if l==0 else 100-100/(1+g/l)

def daily_regime(d,t):
 rows=[x for x in d if x['t']<=t]
 if len(rows)<50:return 'UNKNOWN'
 c=[x['c'] for x in rows[-50:]];e20=ema(c[-20:],20);e50=ema(c,50)
 if e20>e50*1.002:return 'BULL'
 if e20<e50*.998:return 'BEAR'
 return 'SIDEWAYS'

def feat(b,i):
 c=[x['c'] for x in b[i-50:i+1]];p=c[-1];e20=ema(c[-20:],20);e50=ema(c,50);r=rsi(c);sup=min(c[-20:]);res=max(c[-20:]);avg=sum(c[-20:])/20;vol=b[i]['v'];va=sum(x['v'] for x in b[i-20:i])/20
 return p,e20,e50,r,sup,res,avg,vol,va

def rules(x):
 p,e20,e50,r,sup,res,avg,vol,va=x;bull=e20>e50;near=(p-sup)/p<=.015;entry=sup<=p<=sup*1.005;mid=(sup+sup*1.005)/2;rr=(res-mid)/(mid-sup*.99) if sup>0 else 0
 quality=(25 if bull else 0)+(20 if 40<=r<=55 else 18 if r<35 else 15 if r<=65 else 5)+(20 if near else 10 if (p-sup)/p<=.03 else 0)+(15 if entry else 5 if p<=sup*1.01 else 0)+(20 if rr>=2 else 15 if rr>=1.5 else 10 if rr>=1 else 0)
 return {'baseline':bull and near and r<65 and rr>=1 and quality>=65 and entry,'trend_pullback':bull and .97*e20<=p<=1.01*e20 and r<65 and rr>=1,'support_rsi':near and r<45 and entry and rr>=1,'reclaim':bull and p>=e20 and p<=e20*1.01 and r<60 and rr>=1,'momentum':bull and p>avg*1.01 and vol>=1.5*va and rr>=1}

def outcome(b,i):
 if i+1+HORIZON>=len(b):return None
 en=b[i+1]['o']*(1+SLIP);z=b[i+1:i+1+HORIZON];return z[-1]['c']*(1-SLIP)/en-1,max(q['h']*(1-SLIP)/en-1 for q in z),min(q['l']*(1-SLIP)/en-1 for q in z)

def stats(rows):
 if not rows:return {'trades':0,'win_rate_pct':None,'expectancy_pct':None,'profit_factor':None}
 r=[x[0] for x in rows];w=[x for x in r if x>0];loss=-sum(x for x in r if x<0);pf=sum(w)/loss if loss else None
 return {'trades':len(r),'win_rate_pct':round(100*len(w)/len(r),2),'expectancy_pct':round(100*sum(r)/len(r),4),'profit_factor':round(pf,3) if pf is not None else None}

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--months',type=int,default=24);a=ap.parse_args();end=datetime.now(timezone.utc);start=end-timedelta(days=30.44*a.months);result={}
 for s in SYMBOLS:
  try:h=fetch(H.format(s=s),start,end);d=fetch(D.format(s=s),start,end)
  except Exception as e:result[s]={'error':str(e)};continue
  if len(h)<1000 or len(d)<50:result[s]={'error':f'insufficient 1h={len(h)} 1d={len(d)}'};continue
  events=[]
  for i in range(51,len(h)-HORIZON):
   o=outcome(h,i)
   if o:events.append((h[i]['t'],daily_regime(d,h[i]['t']),o,rules(feat(h,i))))
  n=len(events);start_i=max(0,n//5);block=max(1,(n-start_i)//4);modes={'1H_ONLY':lambda e:True,'1D_BULL_FILTER':lambda e:e[1]=='BULL'};summary={}
  for mode,allow in modes.items():
   by_rule={}
   for rule in RULES:
    folds=[]
    for f in range(4):
     lo=start_i+f*block;hi=start_i+(f+1)*block if f<3 else n
     # Training is strictly before the fold; selection is not allowed to use this fold.
     train=events[start_i:lo];test=events[lo:hi]
     tr=[e[2] for e in train if allow(e) and e[3].get(rule)];te=[e[2] for e in test if allow(e) and e[3].get(rule)]
     folds.append({'train':stats(tr),'test':stats(te)})
    all_test=[]
    for f in range(4):
     lo=start_i+f*block;hi=start_i+(f+1)*block if f<3 else n
     all_test += [e[2] for e in events[lo:hi] if allow(e) and e[3].get(rule)]
    passed=sum(1 for f in folds if f['train']['trades']>=10 and f['test']['trades']>=10 and (f['train']['profit_factor'] or 0)>1 and (f['train']['expectancy_pct'] or -999)>0 and (f['test']['profit_factor'] or 0)>1 and (f['test']['expectancy_pct'] or -999)>0)
    overall=stats(all_test);by_rule[rule]={'folds':folds,'passed_folds':passed,'combined_test':overall,'robust':passed>=3 and overall['trades']>=50 and (overall['profit_factor'] or 0)>1.05 and (overall['expectancy_pct'] or -999)>0}
   good=[(v['combined_test']['expectancy_pct'],k,v) for k,v in by_rule.items() if v['robust']];good.sort(reverse=True);summary[mode]={'rules':by_rule,'selected':good[0][1] if good else None}
  result[s]={'candles_1h':len(h),'candles_1d':len(d),'events':n,'summary':summary}
 out={'version':'7.1.0','purpose':'MULTI_TIMEFRAME_WALK_FORWARD_RESEARCH','source':'BINANCE_DATA_ARCHIVE','months':a.months,'entry_interval':'1h','context_interval':'1d','horizon_hours':HORIZON,'costs':{'fee_per_side':FEE,'slippage_per_side':SLIP},'comparison':['1H_ONLY','1D_BULL_FILTER'],'robust_gate':'>=3/4 chronological folds, >=50 combined test trades, PF>1.05, positive expectancy','production_changed':False,'results':result}
 open('backtest_coin_specific_results.json','w').write(json.dumps(out,indent=2));print(json.dumps(out,indent=2))
if __name__=='__main__':main()
