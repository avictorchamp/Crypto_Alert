#!/usr/bin/env python3
"""V7.4 research-only momentum gate sensitivity experiment.
Same Binance archive data, same costs, same 1D BULL context and 24h outcome.
Only the momentum price/volume gate is varied. No production changes.
"""
from __future__ import annotations
import io,json,time,zipfile
from datetime import datetime,timedelta,timezone
from urllib.request import Request,urlopen
from backtest_coin_specific import H,D,HORIZON,feat,fetch,daily_regime,outcome

TARGETS=["BTCUSDT","ETHUSDT","SOLUSDT","XRPUSDT"]
VARIANTS={
 "baseline":"p>avg*1.01 AND vol>=1.5x",
 "price_relaxed":"p>avg*1.005 AND vol>=1.5x",
 "volume_relaxed":"p>avg*1.01 AND vol>=1.2x",
 "price_only":"p>avg*1.01 AND RR>=1",
 "volume_only":"vol>=1.5x AND RR>=1",
 "both_relaxed":"p>avg*1.005 AND vol>=1.2x",
}

def gate(x,variant):
 p,e20,e50,r,sup,res,avg,vol,va=x
 rr=(res-((sup+sup*1.005)/2))/((((sup+sup*1.005)/2)-sup*.99)) if sup>0 else 0
 if variant=="baseline": return p>avg*1.01 and vol>=1.5*va and rr>=1
 if variant=="price_relaxed": return p>avg*1.005 and vol>=1.5*va and rr>=1
 if variant=="volume_relaxed": return p>avg*1.01 and vol>=1.2*va and rr>=1
 if variant=="price_only": return p>avg*1.01 and rr>=1
 if variant=="volume_only": return vol>=1.5*va and rr>=1
 if variant=="both_relaxed": return p>avg*1.005 and vol>=1.2*va and rr>=1
 raise ValueError(variant)

def stats(rows):
 if not rows:return {"trades":0,"win_rate_pct":None,"expectancy_pct":None,"profit_factor":None}
 r=[z[0] for z in rows];w=[z for z in r if z>0];loss=-sum(z for z in r if z<0)
 pf=sum(w)/loss if loss else None
 return {"trades":len(r),"win_rate_pct":round(100*len(w)/len(r),2),"expectancy_pct":round(100*sum(r)/len(r),4),"profit_factor":round(pf,3) if pf is not None else None}

def run_symbol(symbol,end):
 start=end-timedelta(days=30.44*18)
 h=fetch(H,symbol,start,end);d=fetch(D,symbol,start,end)
 events=[]
 for i in range(51,len(h)-HORIZON):
  o=outcome(h,i)
  if o is None: continue
  if daily_regime(d,h[i]["t"])!="BULL": continue
  events.append((h[i]["t"],o,feat(h,i)))
 n=len(events); start_i=n//10
 usable=n-start_i; block=max(1,usable//6)
 out={"events_bull":n,"variants":{}}
 for name in VARIANTS:
  windows=[];all_rows=[]
  for w in range(6):
   lo=start_i+w*block; hi=start_i+(w+1)*block if w<5 else n
   rows=[events[i][1] for i in range(lo,hi) if gate(events[i][2],name)]
   windows.append(stats(rows)); all_rows.extend(rows)
  positive=sum(1 for z in windows if (z["expectancy_pct"] or -999)>0 and (z["profit_factor"] or 0)>1)
  overall=stats(all_rows)
  out["variants"][name]={"positive_windows":positive,"windows":windows,"overall":overall,
    "confirmation_like":positive>=4 and overall["trades"]>=75 and (overall["profit_factor"] or 0)>1.05 and (overall["expectancy_pct"] or -999)>0}
 return out

def main():
 end=datetime.now(timezone.utc)
 out={"version":"7.4.0-gate-sensitivity","production_changed":False,"period_months":18,"targets":TARGETS,"variants":VARIANTS,"results":{}}
 for s in TARGETS:
  try: out["results"][s]=run_symbol(s,end)
  except Exception as e: out["results"][s]={"error":str(e)}
 print(json.dumps(out,indent=2))
 with open("v7_4_gate_sensitivity_results.json","w") as f: json.dump(out,f,indent=2)

if __name__=="__main__": main()
