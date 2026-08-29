#!/usr/bin/env python3
"""V7.4 BNB paper-forward recorder. Research only.
Uses Binance Vision monthly archives with daily fallback.
"""
from __future__ import annotations
import io,json,os,time,zipfile
from datetime import datetime,timedelta,timezone
from urllib.error import HTTPError
from urllib.request import Request,urlopen
SYMBOL='BNBUSDT'; HORIZON=24; FEE=.001; SLIP=.0005
MH='https://data.binance.vision/data/spot/monthly/klines/{s}/1h/{s}-1h-{m}.zip'; MD='https://data.binance.vision/data/spot/monthly/klines/{s}/1d/{s}-1d-{m}.zip'
DH='https://data.binance.vision/data/spot/daily/klines/{s}/1h/{s}-1h-{date}.zip'; DD='https://data.binance.vision/data/spot/daily/klines/{s}/1d/{s}-1d-{date}.zip'
LOG='paper_forward_v7_4_log.json'
def months(a,b):
 y,m=a.year,a.month
 while (y,m)<=(b.year,b.month):
  yield f'{y:04d}-{m:02d}'; m+=1
  if m==13:y+=1;m=1
def days(a,b):
 x=a
 while x.date()<=b.date():yield x.strftime('%Y-%m-%d');x+=timedelta(days=1)
def get(u):
 try:
  with urlopen(Request(u,headers={'User-Agent':'CryptoAlert-PaperForward/7.4'}),timeout=30) as r:return r.read()
 except HTTPError as e:
  if e.code==404:return None
  raise
def read(data,start,end,out):
 with zipfile.ZipFile(io.BytesIO(data)) as z:
  names=[n for n in z.namelist() if n.lower().endswith('.csv')]
  if not names:return
  with z.open(names[0]) as f:
   for raw in f:
    a=raw.decode().strip().split(',')
    if len(a)<6 or not a[0].isdigit():continue
    t=int(a[0]);
    while t>10_000_000_000_000:t//=1000
    dt=datetime.fromtimestamp(t/1000,timezone.utc)
    if start<=dt<=end:out.append({'t':t,'o':float(a[1]),'h':float(a[2]),'l':float(a[3]),'c':float(a[4]),'v':float(a[5])})
def fetch(kind,start,end):
 out=[]; mu=MH if kind=='1h' else MD; du=DH if kind=='1h' else DD
 for mo in months(start,end):
  data=get(mu.format(s=SYMBOL,m=mo))
  if data:read(data,start,end,out);continue
  ma=datetime.strptime(mo+'-01','%Y-%m-%d').replace(tzinfo=timezone.utc); mb=(ma+timedelta(days=32)).replace(day=1)-timedelta(seconds=1)
  for ds in days(max(start,ma),min(end,mb)):
   data=get(du.format(s=SYMBOL,date=ds))
   if data:read(data,start,end,out)
 out.sort(key=lambda x:x['t']);return out
def ema(v,p):
 k=2/(p+1);x=v[0]
 for q in v[1:]:x=q*k+x*(1-k)
 return x
def rsi(v,p=14):
 g=sum(max(b-a,0) for a,b in zip(v[-p-1:-1],v[-p:]));l=sum(max(a-b,0) for a,b in zip(v[-p-1:-1],v[-p:]))
 return 50 if g+l==0 else 100 if l==0 else 100-100/(1+g/l)
def regime(d):
 c=[x['c'] for x in d[-50:]];e20=ema(c[-20:],20);e50=ema(c,50)
 return 'BULL' if e20>e50*1.002 else 'BEAR' if e20<e50*.998 else 'SIDEWAYS'
def signal(h,d):
 c=[x['c'] for x in h[-51:]];p=c[-1];avg=sum(c[-20:])/20;e20=ema(c[-20:],20);e50=ema(c[-50:],50);rr=rsi(c);vol=h[-1]['v'];va=sum(x['v'] for x in h[-21:-1])/20;support=min(c[-20:]);resistance=max(c[-20:]);den=p-support*.99;ratio=(resistance-p)/den if support>0 and den>0 else 0;reg=regime(d)
 return {'signal':reg=='BULL' and e20>e50 and p>avg*1.01 and vol>=1.5*va and ratio>=1,'price':p,'regime':reg,'rsi':rr,'volume_ratio':vol/va if va else None,'risk_reward':ratio,'ema20':e20,'ema50':e50}
def main():
 end=datetime.now(timezone.utc);start=end-timedelta(days=75);h=fetch('1h',start,end);d=fetch('1d',start,end)
 if len(h)<51 or len(d)<50:raise RuntimeError(f'insufficient data 1h={len(h)} 1d={len(d)}')
 data={'version':'7.4.0','purpose':'BNB_PAPER_FORWARD','symbol':SYMBOL,'rule':'momentum','context':'1D_BULL_FILTER','horizon_hours':HORIZON,'observations':[],'production_changed':False}
 if os.path.exists(LOG):
  with open(LOG) as f:data=json.load(f)
 s=signal(h,d);last=h[-1]
 if not any(x.get('signal_candle_close_ms')==last['t'] for x in data['observations']):data['observations'].append({'signal_time_utc':datetime.fromtimestamp(last['t']/1000,timezone.utc).isoformat(),'signal_candle_close_ms':last['t'],'signal':bool(s['signal']),'price':s['price'],'regime':s['regime'],'rsi':s['rsi'],'volume_ratio':s['volume_ratio'],'risk_reward':s['risk_reward'],'status':'OPEN' if s['signal'] else 'NO_TRADE'})
 closed=[x['paper_return_pct'] for x in data['observations'] if x.get('status')=='CLOSED'];wins=[x for x in closed if x>0];loss=-sum(x for x in closed if x<0)
 data['summary']={'closed_trades':len(closed),'win_rate_pct':round(100*len(wins)/len(closed),2) if closed else None,'expectancy_pct':round(sum(closed)/len(closed),4) if closed else None,'profit_factor':round(sum(wins)/loss,3) if loss else None}
 with open(LOG,'w') as f:json.dump(data,f,indent=2)
 print(json.dumps({'latest_signal':s,'summary':data['summary'],'observations':len(data['observations']),'candles_1h':len(h),'candles_1d':len(d)},indent=2))
if __name__=='__main__':main()
