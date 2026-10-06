#!/usr/bin/env python3
"""V7.18 SOL LONG 48h rolling + net cost final gate. Research only."""
from __future__ import annotations
import json
from datetime import datetime,timedelta,timezone
from v7_6_coin_fingerprint import fetch,D,collect,learn_patterns
from v7_13_shadow_signal_simulation import freeze_rules,cond_match
SYMBOL="SOLUSDT"; HORIZON=48; WINDOW_DAYS=30; WINDOWS=3
COST=.002; MIN_WINDOW_SIGNALS=5; MIN_PASS_WINDOWS=2; MIN_TOTAL=20; MIN_RATE=.50; MIN_NET_AVG=.002
def main():
 end=datetime.now(timezone.utc); freeze=end-timedelta(days=90); start=freeze-timedelta(days=30.44*18+5)
 btc=fetch(D,"BTCUSDT",start,end); hist=collect(SYMBOL,start,freeze,btc); rules=freeze_rules(hist)
 rule=next((r for r in rules if r["direction"]=="LONG" and int(r["horizon"])==HORIZON),None)
 if not rule: raise RuntimeError("Frozen SOL LONG 48h rule not found")
 edges=learn_patterns(hist[:int(len(hist)*.20)])["edges"]; windows=[]; all_net=[]
 for k in range(WINDOWS):
  a=freeze+timedelta(days=k*WINDOW_DAYS); b=a+timedelta(days=WINDOW_DAYS)
  rows=collect(SYMBOL,a,b,btc); m=[r for r in rows if cond_match(r,rule["label"],edges)]
  gross=[r["outcomes"][str(HORIZON)]["close"] for r in m]; net=[x-COST for x in gross]; all_net+=net
  rate=sum(r["outcomes"][str(HORIZON)]["max"]>=.02 for r in m)/len(m) if m else None
  avg=sum(net)/len(net) if net else None
  passed=bool(len(m)>=MIN_WINDOW_SIGNALS and rate>=MIN_RATE and avg>=MIN_NET_AVG)
  windows.append({"window":k+1,"signals":len(m),"directional_rate":rate,"net_avg":avg,"passed":passed})
 n=len(all_net); avg=sum(all_net)/n if n else None; win=sum(x>0 for x in all_net)/n if n else None
 passw=sum(x["passed"] for x in windows)
 passed=bool(passw>=MIN_PASS_WINDOWS and n>=MIN_TOTAL and win>=.50 and avg>=MIN_NET_AVG)
 out={"version":"7.18.0-sol-final-gates","production_changed":False,"symbol":SYMBOL,"direction":"LONG","horizon_hours":HORIZON,
 "pattern":rule["label"],"round_trip_cost":COST,"windows":windows,"pass_windows":passw,"trades":n,"net_win_rate":win,
 "net_avg_return":avg,"final_gate_passed":passed}
 open("v7_18_sol_final_results.json","w").write(json.dumps(out,indent=2)); print(json.dumps(out,indent=2))
if __name__=="__main__": main()
