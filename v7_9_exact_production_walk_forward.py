import json
from datetime import datetime,timedelta,timezone
from backtest_coin_specific import H,fetch,feat
from app.crypto.strategy import generate_signal
TARGETS=["BTCUSDT","ETHUSDT","SOLUSDT","XRPUSDT"]; HORIZON=24
def exact(h,i):
 p,e20,e50,r,sup,res,avg,vol,va=feat(h,i); vr=vol/va if va else None
 mom=(p/h[i-6]["c"]-1) if h[i-6]["c"] else None
 return generate_signal(rsi=r,ema20=e20,ema50=e50,price=p,support=sup,resistance=res,volume_ratio=vr,momentum_6h=mom)
def outcome(h,i):
 z=h[i+1:i+1+HORIZON]
 if len(z)<HORIZON:return None
 en=h[i]["c"]; return {"ret":z[-1]["c"]/en-1,"mfe":max(x["h"] for x in z)/en-1,"mae":min(x["l"] for x in z)/en-1}
def metrics(rs):
 vals=[x["o"]["ret"] for x in rs]; n=len(vals)
 if not n:return {"trades":0,"win_rate":None,"expectancy":None,"pf":None}
 wins=[v for v in vals if v>0]; loss=[-v for v in vals if v<=0]
 return {"trades":n,"win_rate":sum(v>0 for v in vals)/n,"expectancy":sum(vals)/n,"pf":sum(wins)/sum(loss) if loss else None}
def collect(s,start,end):
 h=fetch(H,s,start,end); rs=[]
 for i in range(60,len(h)-HORIZON-1):
  o=outcome(h,i)
  if o:
   z=exact(h,i); rs.append({"signal":z["signal"],"rr":z["risk_reward"],"quality":z["quality_score"],"o":o})
 return rs
def main():
 end=datetime.now(timezone.utc); start=end-timedelta(days=30.44*18); result={}
 for s in TARGETS:
  rs=collect(s,start,end); n=len(rs); folds=[]
  for k in range(4):
   cut=int(n*.20)+int(k*(n*.80/4)); nxt=int(n*.20)+int((k+1)*(n*.80/4)); test=rs[cut:nxt]
   buys=[x for x in test if x["signal"] in ("BUY SETUP","STRONG BUY")]
   folds.append({"fold":k+1,"test_events":len(test),"production_buy_signals":metrics(buys),"signal_counts":{q:sum(x["signal"]==q for x in test) for q in ["STRONG BUY","BUY SETUP","WAIT","SELL WATCH"]}})
  result[s]={"events":n,"folds":folds}
 out={"version":"7.9.0-exact-production-gate-walk-forward","production_changed":False,"period_months":18,"horizon_hours":24,"split":"4 chronological unseen folds after 20% warmup","production_source":"main app.crypto.strategy.generate_signal and app.crypto.indicators","pass_reference":"trades>=30, PF>1.05, expectancy>0","results":result}
 open("v7_9_exact_production_results.json","w").write(json.dumps(out,indent=2)); print(json.dumps(out,indent=2))
if __name__=="__main__": main()
