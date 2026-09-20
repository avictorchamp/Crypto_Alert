#!/usr/bin/env python3
import json
from datetime import datetime,timedelta,timezone
from backtest_coin_specific import H,D,feat,fetch,daily_regime

TARGETS=["BTCUSDT","ETHUSDT","SOLUSDT","XRPUSDT"]
HORIZON=24
def row(h,d,i,btc_d):
 p,e20,e50,r,sup,res,avg,vol,va=feat(h,i)
 c=h[i]["c"]; m20=c/h[i-20]["c"]-1
 return {"t":h[i]["t"],"p":p,"rsi":r,"vol_ratio":vol/va if va else 0,"mom":m20,
 "ema_dist":p/e20-1 if e20 else 0,"h1":p>e20,"d1":daily_regime(d,h[i]["t"]),
 "btc":daily_regime(btc_d,h[i]["t"])}
def outcome(h,i):
 z=h[i+1:i+1+HORIZON]; en=h[i]["c"]
 if len(z)<HORIZON:return None
 return {"ret":z[-1]["c"]/en-1,"mfe":max(x["h"] for x in z)/en-1,"mae":min(x["l"] for x in z)/en-1}
def collect(s,start,end,btc_d):
 h=fetch(H,s,start,end);d=fetch(D,s,start,end);rs=[]
 for i in range(60,len(h)-HORIZON-1):
  o=outcome(h,i)
  if o:rs.append({"x":row(h,d,i,btc_d),"o":o})
 return rs
def gate(x): return x["d1"]=="BULL" and x["h1"] and x["mom"]>.01 and x["vol_ratio"]>=1.2
def variants(x):
 return {
 "baseline":gate(x),
 "btc_regime":gate(x) and x["btc"]=="BULL",
 "coin_trend":gate(x) and x["ema_dist"]>0,
 "momentum":gate(x) and x["mom"]>.015,
 "volume":gate(x) and x["vol_ratio"]>=1.5,
 "trend_btc":gate(x) and x["btc"]=="BULL" and x["ema_dist"]>0,
 }
def metrics(rows):
 n=len(rows)
 if not n:return {"trades":0,"win_rate":None,"expectancy":None,"pf":None}
 wins=[r["o"]["ret"] for r in rows if r["o"]["ret"]>0];loss=[-r["o"]["ret"] for r in rows if r["o"]["ret"]<=0]
 return {"trades":n,"win_rate":sum(r["o"]["ret"]>0 for r in rows)/n,
 "expectancy":sum(r["o"]["ret"] for r in rows)/n,"pf":sum(wins)/sum(loss) if loss else None}
def evalv(rows,name): return metrics([r for r in rows if variants(r["x"])[name]])
def main():
 end=datetime.now(timezone.utc);start=end-timedelta(days=30.44*18);btc=fetch(D,"BTCUSDT",start,end)
 allr={s:collect(s,start,end,btc) for s in TARGETS};out={}
 for s,rs in allr.items():
  n=len(rs);folds=[]
  # 4 expanding folds; variant selected on prior data, then tested once.
  for k in range(4):
   cut=int(n*.20)+int(k*(n*.80/4)); nxt=int(n*.20)+int((k+1)*(n*.80/4))
   train=rs[:cut];test=rs[cut:nxt]
   scores={v:evalv(train,v) for v in variants(rs[0]["x"])}
   eligible=[v for v,m in scores.items() if m["trades"]>=30 and m["expectancy"]>0 and (m["pf"] or 0)>1]
   selected=max(eligible,key=lambda v:(scores[v]["expectancy"],scores[v]["pf"])) if eligible else "baseline"
   folds.append({"fold":k+1,"train":len(train),"test":len(test),"selected":selected,
    "selected_test":evalv(test,selected),"baseline_test":evalv(test,"baseline"),"training_scores":scores})
  out[s]={"events":n,"folds":folds}
 result={"version":"7.7.0-coin-specific-strategy","production_changed":False,
 "rule":"select coin-specific variant from prior data only; test on next chronological fold",
 "pass":"trades>=30, PF>1.05, expectancy>0","results":out}
 open("v7_7_coin_specific_strategy_results.json","w").write(json.dumps(result,indent=2))
 print(json.dumps(result,indent=2))
if __name__=="__main__":main()
