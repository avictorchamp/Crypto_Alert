#!/usr/bin/env python3
"""V7.4 multi-coin paper-forward recorder. Research only; never trades live.

The strategy is unchanged from V7.4 BNB:
1D_BULL_FILTER + 1H momentum, 24h horizon.
Each symbol has an independent cumulative log.
"""
from __future__ import annotations
import io,json,os,zipfile
from datetime import datetime,timedelta,timezone
from urllib.error import HTTPError
from urllib.request import Request,urlopen

SYMBOL=os.environ.get("PAPER_FORWARD_SYMBOL","").strip().upper()
ALLOWED={"BTCUSDT","ETHUSDT","SOLUSDT","XRPUSDT"}
if SYMBOL not in ALLOWED: raise RuntimeError(f"unsupported symbol: {SYMBOL}")
HORIZON_HOURS=24
FEE=0.001
SLIPPAGE=0.0005
FORWARD_TEST_START_UTC="2026-08-28T23:00:00+00:00"
LOG_FILE=f"paper_forward_v7_4_{SYMBOL}_log.json"
M1H="https://data.binance.vision/data/spot/monthly/klines/{symbol}/1h/{symbol}-1h-{month}.zip"
M1D="https://data.binance.vision/data/spot/monthly/klines/{symbol}/1d/{symbol}-1d-{month}.zip"
D1H="https://data.binance.vision/data/spot/daily/klines/{symbol}/1h/{date}.zip"
D1D="https://data.binance.vision/data/spot/daily/klines/{symbol}/1d/{date}.zip"

def parse_iso(v): return datetime.fromisoformat(v.replace("Z","+00:00"))
def months(a,b):
 y,m=a.year,a.month
 while (y,m)<=(b.year,b.month):
  yield f"{y:04d}-{m:02d}"; m+=1
  if m==13: y,m=y+1,1
def days(a,b):
 while a.date()<=b.date(): yield a.strftime("%Y-%m-%d"); a+=timedelta(days=1)
def get(url):
 try:
  with urlopen(Request(url,headers={"User-Agent":"CryptoAlert-PaperForward/7.4"}),timeout=30) as r:return r.read()
 except HTTPError as e:
  if e.code==404:return None
  raise
def read_zip(data,start,end,out):
 with zipfile.ZipFile(io.BytesIO(data)) as z:
  names=[n for n in z.namelist() if n.lower().endswith('.csv')]
  if not names:return
  with z.open(names[0]) as f:
   for raw in f:
    x=raw.decode().strip().split(',')
    if len(x)<6 or not x[0].isdigit():continue
    t=int(x[0])
    while t>10_000_000_000_000:t//=1000
    dt=datetime.fromtimestamp(t/1000,timezone.utc)
    if start<=dt<=end:out.append({"t":t,"o":float(x[1]),"h":float(x[2]),"l":float(x[3]),"c":float(x[4]),"v":float(x[5])})
def fetch(kind,start,end):
 out=[]; mu,du=(M1H,D1H) if kind=='1h' else (M1D,D1D)
 for month in months(start,end):
  data=get(mu.format(symbol=SYMBOL,month=month))
  if data is not None: read_zip(data,start,end,out); continue
  ms=datetime.strptime(month+'-01','%Y-%m-%d').replace(tzinfo=timezone.utc)
  me=(ms+timedelta(days=32)).replace(day=1)-timedelta(seconds=1)
  for date in days(max(start,ms),min(end,me)):
   data=get(du.format(symbol=SYMBOL,date=date))
   if data is not None:read_zip(data,start,end,out)
 return sorted({x['t']:x for x in out}.values(),key=lambda x:x['t'])
def ema(v,p):
 k=2/(p+1); e=v[0]
 for x in v[1:]:e=x*k+e*(1-k)
 return e
def rsi(v,p=14):
 gains=sum(max(b-a,0) for a,b in zip(v[-p-1:-1],v[-p:])); losses=sum(max(a-b,0) for a,b in zip(v[-p-1:-1],v[-p:]))
 if gains+losses==0:return 50
 if losses==0:return 100
 return 100-100/(1+gains/losses)
def regime(d):
 c=[x['c'] for x in d[-50:]]; e20=ema(c[-20:],20); e50=ema(c,50)
 return 'BULL' if e20>e50*1.002 else 'BEAR' if e20<e50*.998 else 'SIDEWAYS'
def signal(h,d):
 c=[x['c'] for x in h[-51:]]; p=c[-1]; avg=sum(c[-20:])/20; e20=ema(c[-20:],20); e50=ema(c[-50:],50); rv=rsi(c); vr=h[-1]['v']/(sum(x['v'] for x in h[-21:-1])/20)
 s=min(c[-20:]); r=max(c[-20:]); den=p-s*.99; rr=(r-p)/den if s>0 and den>0 else 0; rg=regime(d)
 ok=rg=='BULL' and e20>e50 and p>avg*1.01 and vr>=1.5 and rr>=1
 return {"signal":ok,"price":p,"regime":rg,"rsi":rv,"volume_ratio":vr,"risk_reward":rr,"ema20":e20,"ema50":e50}
def close_ready(obs,h):
 horizon=HORIZON_HOURS*3600000
 by={x['t']:x for x in h}
 for o in obs:
  if o.get('status')!='OPEN' or not o.get('signal'):continue
  target=int(o['signal_candle_close_ms'])+horizon
  future=[t for t in by if t>=target]
  if not future:continue
  x=by[min(future)]; entry=float(o['price']); gross=(x['c']/entry-1)*100; net=gross-(FEE+SLIPPAGE)*100
  o.update(exit_time_utc=datetime.fromtimestamp(x['t']/1000,timezone.utc).isoformat(),exit_price=x['c'],paper_return_pct=round(net,4),status='CLOSED')
def summary(obs):
 ret=[float(o['paper_return_pct']) for o in obs if o.get('status')=='CLOSED']; win=[x for x in ret if x>0]; loss=[x for x in ret if x<0]; n=len(ret); avg=sum(ret)/n if n else None; pf=sum(win)/(-sum(loss)) if loss else None
 eq=peak=1.; dd=0.
 for x in ret:
  eq*=1+x/100; peak=max(peak,eq); dd=max(dd,(peak-eq)/peak*100)
 return {"closed_trades":n,"winning_trades":len(win),"losing_trades":len(loss),"win_rate_pct":round(100*len(win)/n,2) if n else None,"average_return_pct":round(avg,4) if avg is not None else None,"expectancy_pct":round(avg,4) if avg is not None else None,"profit_factor":round(pf,3) if pf is not None else None,"max_drawdown_pct":round(dd,4),"open_trades":sum(o.get('status')=='OPEN' for o in obs)}
def main():
 now=datetime.now(timezone.utc); start=parse_iso(FORWARD_TEST_START_UTC); data_start=start-timedelta(days=90)
 h=fetch('1h',data_start,now); d=fetch('1d',data_start,now)
 if len(h)<51:raise RuntimeError(f'insufficient 1H data: {len(h)}')
 if len(d)<50:raise RuntimeError(f'insufficient 1D data: {len(d)}')
 data={"version":"7.4.0","purpose":"MULTI_COIN_PAPER_FORWARD","symbol":SYMBOL,"rule":"momentum","context":"1D_BULL_FILTER","horizon_hours":HORIZON_HOURS,"forward_test_start_utc":FORWARD_TEST_START_UTC,"observations":[],"production_changed":False}
 if os.path.exists(LOG_FILE):
  with open(LOG_FILE,encoding='utf-8') as f:data=json.load(f)
  if data.get('symbol')!=SYMBOL or data.get('rule')!='momentum' or data.get('context')!='1D_BULL_FILTER' or data.get('forward_test_start_utc')!=FORWARD_TEST_START_UTC or data.get('production_changed') is not False:raise RuntimeError('paper log safety check failed')
  data.setdefault('observations',[])
 known={int(o['signal_candle_close_ms']) for o in data['observations']}
 # Canonical observation: 23:00 UTC completed 1H candle; daily regime uses only daily candles before observation day.
 start_ms=int(start.timestamp()*1000)
 for x in h:
  dt=datetime.fromtimestamp(x['t']/1000,timezone.utc)
  if dt<start or dt.hour!=23 or x['t'] in known:continue
  day_start=dt.replace(hour=0,minute=0,second=0,microsecond=0)
  hd=[c for c in h if c['t']<=x['t']]
  dd=[c for c in d if c['t']<int(day_start.timestamp()*1000)]
  if len(hd)<51 or len(dd)<50:continue
  s=signal(hd,dd); data['observations'].append({"signal_time_utc":dt.isoformat(),"signal_candle_close_ms":x['t'],**s,"status":"OPEN" if s['signal'] else 'NO_TRADE'})
 data['observations'].sort(key=lambda o:int(o['signal_candle_close_ms']))
 close_ready(data['observations'],h); data['summary']=summary(data['observations']); data['last_run_utc']=now.isoformat(); data['latest_observation_utc']=max((o['signal_time_utc'] for o in data['observations']),default=None); data['candles_1h']=len(h); data['candles_1d']=len(d)
 with open(LOG_FILE,'w',encoding='utf-8') as f:json.dump(data,f,indent=2)
 print(json.dumps({"symbol":SYMBOL,"observations":len(data['observations']),"summary":data['summary'],"latest_observation_utc":data['latest_observation_utc'],"production_changed":False},indent=2))
if __name__=='__main__':main()
