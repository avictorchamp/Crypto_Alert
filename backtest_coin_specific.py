#!/usr/bin/env python3
"""V7 robust coin-specific research backtest. Research only; never trades."""
from __future__ import annotations
import argparse,csv,io,json,time,zipfile
from datetime import datetime,timedelta,timezone
from urllib.request import Request,urlopen

SYMBOLS=['BTCUSDT','ETHUSDT','XRPUSDT','SOLUSDT','BNBUSDT','ADAUSDT','DOGEUSDT','LINKUSDT','AVAXUSDT']
ARCHIVE='https://data.binance.vision/data/spot/monthly/klines/{symbol}/1h/{symbol}-1h-{month}.zip'
FEE=.001;SLIP=.0005;HORIZON=24
RULES=('baseline','trend_pullback','support_rsi','reclaim','momentum')


def months_between(start,end):
    y,m=start.year,start.month
    while (y,m)<=(end.year,end.month):
        yield f'{y:04d}-{m:02d}'
        m+=1
        if m==13:y+=1;m=1


def parse_ts(raw):
    ts=int(raw)
    while ts>10_000_000_000_000: ts//=1000
    return ts


def fetch(symbol,start,end):
    rows=[]
    for month in months_between(start,end):
        try:
            with urlopen(Request(ARCHIVE.format(symbol=symbol,month=month),headers={'User-Agent':'CryptoAlert-Research/1.0'}),timeout=60) as r:data=r.read()
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                with z.open(z.namelist()[0]) as fh:
                    for raw in fh:
                        row=raw.decode().strip().split(',')
                        if len(row)<6 or not row[0].isdigit(): continue
                        ts=parse_ts(row[0]);dt=datetime.fromtimestamp(ts/1000,timezone.utc)
                        if start<=dt<=end:
                            rows.append({'t':ts,'o':float(row[1]),'h':float(row[2]),'l':float(row[3]),'c':float(row[4]),'v':float(row[5])})
        except Exception as e:
            if '404' not in str(e): raise RuntimeError(f'{symbol} {month}: {e}')
        time.sleep(.02)
    rows.sort(key=lambda x:x['t']);return rows


def ema(v,p):
    k=2/(p+1);x=v[0]
    for z in v[1:]: x=z*k+x*(1-k)
    return x


def rsi(v,p=14):
    g=sum(max(b-a,0) for a,b in zip(v[-p-1:-1],v[-p:]));l=sum(max(a-b,0) for a,b in zip(v[-p-1:-1],v[-p:]))
    return 50 if g+l==0 else 100 if l==0 else 100-100/(1+g/l)


def feat(b,i):
    c=[x['c'] for x in b[i-50:i+1]];p=c[-1];e20=ema(c[-20:],20);e50=ema(c,50);rr=rsi(c);sup=min(c[-20:]);res=max(c[-20:]);avg=sum(c[-20:])/20;va=sum(x['v'] for x in b[i-20:i])/20
    return p,e20,e50,rr,sup,res,avg,b[i]['v'],va


def regime(p,e20,e50):
    if e20>e50*1.002:return 'BULL'
    if e20<e50*.998:return 'BEAR'
    return 'SIDEWAYS'


def signals(x):
    p,e20,e50,rr,sup,res,avg,vol,va=x;bull=e20>e50;near=(p-sup)/p<=.015;entry=sup<=p<=sup*1.005;mid=(sup+sup*1.005)/2;rratio=(res-mid)/(mid-sup*.99) if sup>0 else 0
    quality=(25 if bull else 0)+(20 if 40<=rr<=55 else 18 if rr<35 else 15 if rr<=65 else 5)+(20 if near else 10 if (p-sup)/p<=.03 else 0)+(15 if entry else 5 if p<=sup*1.01 else 0)+(20 if rratio>=2 else 15 if rratio>=1.5 else 10 if rratio>=1 else 0)
    return {
      'baseline':bull and near and rr<65 and rratio>=1 and quality>=65 and entry,
      'trend_pullback':bull and .97*e20<=p<=1.01*e20 and rr<65 and rratio>=1,
      'support_rsi':near and rr<45 and entry and rratio>=1,
      'reclaim':bull and p>=e20 and p<=e20*1.01 and rr<60 and rratio>=1,
      'momentum':bull and p>avg*1.01 and vol>=1.5*va and rratio>=1,
    }


def outcome(b,i):
    if i+1+HORIZON>=len(b): return None
    entry=b[i+1]['o']*(1+SLIP);z=b[i+1:i+1+HORIZON]
    ret=z[-1]['c']*(1-SLIP)/entry-1
    best=max(q['h']*(1-SLIP)/entry-1 for q in z)
    worst=min(q['l']*(1-SLIP)/entry-1 for q in z)
    return ret,best,worst


def stats(rows):
    if not rows:return {'trades':0,'win_rate_pct':None,'expectancy_pct':None,'profit_factor':None,'avg_best_pct':None,'avg_worst_pct':None}
    r=[x[0] for x in rows];wins=[x for x in r if x>0];loss=-sum(x for x in r if x<0);pf=sum(wins)/loss if loss else None
    return {'trades':len(r),'win_rate_pct':round(100*len(wins)/len(r),2),'expectancy_pct':round(100*sum(r)/len(r),4),'profit_factor':round(pf,3) if pf is not None else None,'avg_best_pct':round(100*sum(x[1] for x in rows)/len(rows),3),'avg_worst_pct':round(100*sum(x[2] for x in rows)/len(rows),3)}


def split_folds(n):
    # Four chronological walk-forward test blocks; each block is evaluated out-of-sample.
    start=max(51,n//5)
    usable=n-start-HORIZON
    block=max(1,usable//4)
    return [(start+j*block,start+(j+1)*block if j<3 else n-HORIZON) for j in range(4)]


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--months',type=int,default=24);a=ap.parse_args()
    end=datetime.now(timezone.utc);start=end-timedelta(days=30.44*a.months);allres={}
    for coin in SYMBOLS:
        try:b=fetch(coin,start,end)
        except Exception as e:allres[coin]={'error':str(e)};continue
        if len(b)<1000:allres[coin]={'error':f'insufficient candles: {len(b)}'};continue
        folds=split_folds(len(b)); rule_rows={r:[] for r in RULES}; fold_results=[]; regime_rows={r:{g:[] for g in ('BULL','BEAR','SIDEWAYS')} for r in RULES}
        for fi,(lo,hi) in enumerate(folds,1):
            rows={r:[] for r in RULES}
            for i in range(lo,hi):
                x=feat(b,i);sg=signals(x);o=outcome(b,i)
                if not o:continue
                rg=regime(x[0],x[1],x[2])
                for name,on in sg.items():
                    if on: rows[name].append(o);regime_rows[name][rg].append(o)
            fold_results.append({'fold':fi,'start':datetime.fromtimestamp(b[lo]['t']/1000,timezone.utc).isoformat(),'end':datetime.fromtimestamp(b[min(hi,len(b)-1)]['t']/1000,timezone.utc).isoformat(),'rules':{k:stats(v) for k,v in rows.items()}})
            for k,v in rows.items(): rule_rows[k].extend(v)
        robust={}
        for name in RULES:
            fr=[f['rules'][name] for f in fold_results]
            passed_folds=sum(1 for s in fr if s['trades']>=10 and (s['profit_factor'] or 0)>1 and (s['expectancy_pct'] or -999)>0)
            overall=stats(rule_rows[name]);reg={g:stats(regime_rows[name][g]) for g in regime_rows[name]}
            robust[name]={'overall':overall,'folds':fr,'passed_folds':passed_folds,'regimes':reg,'robust':passed_folds>=3 and overall['trades']>=50 and (overall['profit_factor'] or 0)>1.05 and (overall['expectancy_pct'] or -999)>0}
        candidates=[(k,v) for k,v in robust.items() if v['robust']]
        candidates.sort(key=lambda z:(z[1]['passed_folds'],z[1]['overall']['expectancy_pct'],z[1]['overall']['profit_factor'] or 0),reverse=True)
        selected=candidates[0][0] if candidates else None
        allres[coin]={'candles':len(b),'fold_count':len(folds),'rules':robust,'selected_rule':selected,'decision':'USE_COIN_RULE' if selected else 'AVOID_UNPROVEN'}
    payload={'version':'7.0.0','purpose':'ROBUST_COIN_SPECIFIC_RESEARCH','source':'BINANCE_DATA_ARCHIVE','months':a.months,'interval':'1h','horizon_hours':HORIZON,'costs':{'fee_per_side':FEE,'slippage_per_side':SLIP},'validation':'4 chronological walk-forward out-of-sample folds','robust_rule':'>=3/4 folds with >=10 trades, PF>1, positive expectancy; overall >=50 trades, PF>1.05, positive expectancy','production_changed':False,'results':allres}
    open('backtest_coin_specific_results.json','w').write(json.dumps(payload,indent=2));print(json.dumps(payload,indent=2))

if __name__=='__main__':main()
