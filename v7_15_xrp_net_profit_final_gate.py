#!/usr/bin/env python3
"""V7.15 final research gate for XRP LONG 48h, including fees/slippage.
No automatic trading and no production changes.
"""
from __future__ import annotations
import json
from datetime import datetime,timedelta,timezone
from v7_6_coin_fingerprint import fetch,D,collect,learn_patterns
from v7_13_shadow_signal_simulation import freeze_rules,cond_match

SYMBOL='XRPUSDT'; HORIZON=48; FORWARD_DAYS=90
ROUND_TRIP_COST=0.0020  # conservative 0.20% fee+slippage assumption
MIN_TRADES=20; MIN_WIN_RATE=.50; MIN_NET_AVG=0.002

def main():
    end=datetime.now(timezone.utc); freeze=end-timedelta(days=FORWARD_DAYS)
    start=freeze-timedelta(days=30.44*18+5)
    btc=fetch(D,'BTCUSDT',start,end)
    hist=collect(SYMBOL,start,freeze,btc); forward=collect(SYMBOL,freeze,end,btc)
    rules=freeze_rules(hist)
    rule=next((r for r in rules if r['direction']=='LONG' and int(r['horizon'])==HORIZON),None)
    if rule is None: raise RuntimeError('Frozen XRP LONG 48h rule not found')
    learned=learn_patterns(hist[:int(len(hist)*.20)])
    matches=[r for r in forward if cond_match(r,rule['label'],learned['edges'])]
    gross=[r['outcomes'][str(HORIZON)]['close'] for r in matches]
    net=[x-ROUND_TRIP_COST for x in gross]
    wins=[x>0 for x in net]
    n=len(net); avg=(sum(net)/n if n else None); win=(sum(wins)/n if n else None)
    compounded=1.0
    for x in net: compounded*=1+x
    total_return=compounded-1 if n else None
    passed=bool(n>=MIN_TRADES and win is not None and win>=MIN_WIN_RATE and avg is not None and avg>=MIN_NET_AVG)
    out={'version':'7.15.0-xrp-net-profit-final-gate','production_changed':False,'mode':'SHADOW','integration_status':'NOT_LIVE',
         'symbol':SYMBOL,'direction':'LONG','horizon_hours':HORIZON,'pattern':rule['label'],'forward_days':FORWARD_DAYS,
         'cost_assumption_round_trip':ROUND_TRIP_COST,'trades':n,'net_win_rate':win,'net_avg_return_per_trade':avg,
         'net_compounded_return_sequential':total_return,'criteria':{'min_trades':MIN_TRADES,'min_net_win_rate':MIN_WIN_RATE,'min_net_avg_return':MIN_NET_AVG},
         'final_gate_passed':passed,'note':'Research simulation only; sequential compounding ignores overlapping-position capital constraints.'}
    open('v7_15_xrp_net_profit_results.json','w').write(json.dumps(out,indent=2))
    print(json.dumps(out,indent=2)); print('V7.15 FINAL GATE COMPLETED'); print('PRODUCTION_CHANGED=False')
if __name__=='__main__': main()
