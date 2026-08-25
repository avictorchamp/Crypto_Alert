#!/usr/bin/env python3
"""V7.3 locked-rule stability confirmation.

Rules are copied from the V7.2 TRUE OOS selection and are NOT re-optimized here.
The test evaluates four chronological 3-month windows across the final 12 months
of a 24-month data set. Research only; production is untouched.
"""
from __future__ import annotations
import json
from datetime import datetime, timedelta, timezone
from backtest_coin_specific import SYMBOLS, H, D, FEE, SLIP, HORIZON, fetch, outcome, feat, rules, daily_regime, stats

LOCKED = {
    'BTCUSDT': {'1H_ONLY':'trend_pullback','1D_BULL_FILTER':'reclaim'},
    'ETHUSDT': {'1H_ONLY':'baseline','1D_BULL_FILTER':'baseline'},
    'XRPUSDT': {'1H_ONLY':'momentum','1D_BULL_FILTER':'support_rsi'},
    'SOLUSDT': {'1H_ONLY':'momentum','1D_BULL_FILTER':'momentum'},
    'BNBUSDT': {'1H_ONLY':'momentum','1D_BULL_FILTER':'momentum'},
    'ADAUSDT': {'1H_ONLY':'momentum','1D_BULL_FILTER':'momentum'},
    'DOGEUSDT': {'1H_ONLY':'momentum','1D_BULL_FILTER':'momentum'},
    'LINKUSDT': {'1H_ONLY':'support_rsi','1D_BULL_FILTER':'support_rsi'},
    'AVAXUSDT': {'1H_ONLY':'momentum','1D_BULL_FILTER':'momentum'},
}

def main():
    end=datetime.now(timezone.utc)
    start=end-timedelta(days=30.44*24)
    result={}
    for s in SYMBOLS:
        try:
            h=fetch(H,s,start,end); d=fetch(D,s,start,end)
            if len(h)<1000 or len(d)<50: raise RuntimeError(f'insufficient data 1h={len(h)} 1d={len(d)}')
            events=[]
            for i in range(51,len(h)-HORIZON):
                o=outcome(h,i)
                if o is not None:
                    events.append((h[i]['t'],daily_regime(d,h[i]['t']),o,rules(feat(h,i))))
            cutoff=int((end-timedelta(days=365.28)).timestamp()*1000)
            oos=[e for e in events if e[0]>=cutoff]
            if len(oos)<4: raise RuntimeError(f'not enough OOS events={len(oos)}')
            lo=min(e[0] for e in oos); hi=max(e[0] for e in oos); span=max(1,hi-lo+1)
            windows=[]
            for w in range(4):
                a=lo+(span*w)//4; b=lo+(span*(w+1))//4 if w<3 else hi+1
                windows.append([e for e in oos if a<=e[0]<b])
            summary={}
            for mode,rule in LOCKED[s].items():
                fold=[]; all_rows=[]
                for idx,win in enumerate(windows,1):
                    allow=lambda e: mode=='1H_ONLY' or e[1]=='BULL'
                    rows=[e[2] for e in win if allow(e) and e[3].get(rule)]
                    all_rows.extend(rows); st=stats(rows)
                    fold.append({'window':idx,'start_utc':datetime.fromtimestamp(win[0][0]/1000,timezone.utc).date().isoformat() if win else None,'end_utc':datetime.fromtimestamp(win[-1][0]/1000,timezone.utc).date().isoformat() if win else None,'stats':st,'positive':bool(st['trades'] and (st['expectancy_pct'] or 0)>0 and (st['profit_factor'] or 0)>1.0)})
                combined=stats(all_rows); positive=sum(1 for x in fold if x['positive'])
                summary[mode]={'locked_rule':rule,'windows':fold,'positive_windows':positive,'combined_last_12m':combined,'stability_pass':bool(positive>=3 and combined['trades']>=50 and (combined['profit_factor'] or 0)>1.05 and (combined['expectancy_pct'] or -999)>0)}
            result[s]={'candles_1h':len(h),'candles_1d':len(d),'events':len(events),'summary':summary}
        except Exception as e: result[s]={'error':str(e)}
    out={'version':'7.3.0','purpose':'LOCKED_RULE_STABILITY_CONFIRMATION','rule_source':'V7.2_TRUE_OOS_SELECTION','rules_reoptimized':False,'data_window_months':24,'confirmation_window':'last_12_months','folds':4,'fold_length':'~3_months','entry_interval':'1h','context_interval':'1d','horizon_hours':HORIZON,'costs':{'fee_per_side':FEE,'slippage_per_side':SLIP},'gate':'>=3/4 positive windows, >=50 combined trades, PF>1.05, positive expectancy','production_changed':False,'locked_rules':LOCKED,'results':result}
    open('backtest_v7_3_stability_results.json','w').write(json.dumps(out,indent=2)); print(json.dumps(out,indent=2))
if __name__=='__main__': main()
