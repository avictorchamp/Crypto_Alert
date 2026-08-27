#!/usr/bin/env python3
"""V7.4 BNB paper-forward signal recorder.
Uses the exact locked BNB rule: 1D BULL filter + 1H momentum.
This is observation only: no orders, no Telegram, no production imports.
Each run records the signal-time state and, when prior entries reach 24h,
evaluates their realized paper return from Binance public klines.
"""
from __future__ import annotations
import json, os, time
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen

SYMBOL='BNBUSDT'; INTERVAL='1h'; DAILY='1d'; HORIZON=24; FEE=.001; SLIP=.0005
LOG='paper_forward_v7_4_log.json'


def get_klines(interval, limit=100):
    q=urlencode({'symbol':SYMBOL,'interval':interval,'limit':limit})
    req=Request('https://api.binance.com/api/v3/klines?'+q,headers={'User-Agent':'CryptoAlert-PaperForward/7.4'})
    with urlopen(req,timeout=20) as r: rows=r.read()
    return json.loads(rows)

def ema(v,p):
    k=2/(p+1); x=v[0]
    for q in v[1:]: x=q*k+x*(1-k)
    return x

def rsi(v,p=14):
    g=sum(max(b-a,0) for a,b in zip(v[-p-1:-1],v[-p:])); l=sum(max(a-b,0) for a,b in zip(v[-p-1:-1],v[-p:]))
    return 50 if g+l==0 else 100 if l==0 else 100-100/(1+g/l)

def regime(d):
    c=[float(x[4]) for x in d[-50:]]
    return 'BULL' if ema(c[-20:],20)>ema(c,50)*1.002 else 'BEAR' if ema(c[-20:],20)<ema(c,50)*.998 else 'SIDEWAYS'

def momentum_signal(h):
    c=[float(x[4]) for x in h[-51:]]; p=c[-1]; e20=ema(c[-20:],20); e50=ema(c[-50:],50); rr=rsi(c); avg=sum(c[-20:])/20
    vol=float(h[-1][5]); va=sum(float(x[5]) for x in h[-21:-1])/20
    # Exact V7.1/V7.4 momentum rule body, with the V7.4 1D BULL context filter.
    support=min(c[-20:]); resistance=max(c[-20:]);
    mid=p; rr_ratio=(resistance-mid)/(mid-support*.99) if support>0 and mid-support*.99>0 else 0
    return {'signal': regime(daily_cache)=='BULL' and e20>e50 and p>avg*1.01 and vol>=1.5*va and rr_ratio>=1,
            'price':p,'ema20':e20,'ema50':e50,'rsi':rr,'avg20':avg,'volume':vol,'avg_volume20':va,
            'support20':support,'resistance20':resistance,'risk_reward':rr_ratio}

def load():
    if not os.path.exists(LOG): return {'version':'7.4.0','symbol':SYMBOL,'rule':'momentum','context':'1D_BULL_FILTER','horizon_hours':HORIZON,'observations':[],'production_changed':False}
    with open(LOG) as f: return json.load(f)

def evaluate(obs,h):
    now=int(h[-1][0]); out=[]
    for x in obs:
        if x.get('status')!='OPEN' or now-x['signal_candle_close_ms'] < HORIZON*3600000: continue
        future=[r for r in h if r[0]>x['signal_candle_close_ms']]
        if len(future)<HORIZON: continue
        en=future[0][1]*(1+SLIP); exitp=future[HORIZON-1][4]*(1-SLIP); ret=exitp/en-1-FEE
        x.update({'status':'CLOSED','exit_time_utc':datetime.fromtimestamp(future[HORIZON-1][0]/1000,timezone.utc).isoformat(),'paper_return_pct':round(ret*100,4)})

def main():
    global daily_cache
    h=get_klines(INTERVAL,100); daily_cache=get_klines(DAILY,60)
    data=load(); evaluate(data['observations'],h)
    last=h[-1]; s=momentum_signal(h)
    # one observation per candle close
    if not any(x.get('signal_candle_close_ms')==last[0] for x in data['observations']):
        data['observations'].append({'signal_time_utc':datetime.fromtimestamp(last[0]/1000,timezone.utc).isoformat(),'signal_candle_close_ms':last[0],'signal':bool(s['signal']),'price':s['price'],'regime':'BULL' if regime(daily_cache)=='BULL' else regime(daily_cache),'rsi':s['rsi'],'volume_ratio':s['volume']/s['avg_volume20'] if s['avg_volume20'] else None,'risk_reward':s['risk_reward'],'status':'OPEN' if s['signal'] else 'NO_TRADE'})
    closed=[x['paper_return_pct'] for x in data['observations'] if x.get('status')=='CLOSED']
    wins=[x for x in closed if x>0]; loss=-sum(x for x in closed if x<0); pf=(sum(wins)/loss) if loss else None
    data['summary']={'closed_trades':len(closed),'win_rate_pct':round(100*len(wins)/len(closed),2) if closed else None,'expectancy_pct':round(sum(closed)/len(closed),4) if closed else None,'profit_factor':round(pf,3) if pf is not None else None}
    with open(LOG,'w') as f: json.dump(data,f,indent=2)
    print(json.dumps({'signal':s,'summary':data['summary'],'observations':len(data['observations'])},indent=2))

if __name__=='__main__': main()
