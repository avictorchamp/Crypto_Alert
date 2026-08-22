#!/usr/bin/env python3
"""V7.2 TRUE OUT-OF-SAMPLE validation.

Selects a rule using the first 18 months (train=12m, validation=6m), then
locks that rule and evaluates it once on the final 6 months. Research only.
"""
from __future__ import annotations
import argparse, json
from datetime import datetime, timedelta, timezone
from backtest_coin_specific import SYMBOLS, H, D, FEE, SLIP, HORIZON, RULES, fetch, outcome, feat, rules, daily_regime, stats

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--months',type=int,default=24); a=ap.parse_args()
    end=datetime.now(timezone.utc); start=end-timedelta(days=30.44*a.months)
    train_end=start+timedelta(days=365); val_end=start+timedelta(days=548)
    result={}
    for s in SYMBOLS:
        try:
            h=fetch(H,s,start,end); d=fetch(D,s,start,end)
        except Exception as e:
            result[s]={'error':str(e)}; continue
        events=[(h[i]['t'],daily_regime(d,h[i]['t']),outcome(h,i),rules(feat(h,i))) for i in range(51,len(h)-HORIZON) if outcome(h,i)]
        train=[e for e in events if e[0] < int(train_end.timestamp()*1000)]
        val=[e for e in events if int(train_end.timestamp()*1000) <= e[0] < int(val_end.timestamp()*1000)]
        oos=[e for e in events if e[0] >= int(val_end.timestamp()*1000)]
        summary={}
        for mode in ('1H_ONLY','1D_BULL_FILTER'):
            def allow(e): return mode=='1H_ONLY' or e[1]=='BULL'
            candidates=[]
            for rule in RULES:
                tr=stats([e[2] for e in train if allow(e) and e[3].get(rule)])
                va=stats([e[2] for e in val if allow(e) and e[3].get(rule)])
                candidates.append((va['expectancy_pct'] if va['expectancy_pct'] is not None else -999, va['profit_factor'] or 0, rule, tr, va))
            candidates.sort(reverse=True)
            selected=candidates[0]
            locked=selected[2]
            oos_stat=stats([e[2] for e in oos if allow(e) and e[3].get(locked)])
            summary[mode]={'selection_rule':locked,'selection_train':selected[3],'selection_validation':selected[4],'true_oos':oos_stat,'oos_pass':bool(oos_stat['trades']>=30 and (oos_stat['profit_factor'] or 0)>1.05 and (oos_stat['expectancy_pct'] or -999)>0)}
        result[s]={'candles_1h':len(h),'candles_1d':len(d),'events':len(events),'summary':summary}
    out={'version':'7.2.0','purpose':'TRUE_OUT_OF_SAMPLE_RULE_VALIDATION','data_split':'12m_train_6m_validation_6m_true_oos','selection_locked_before_oos':True,'entry_interval':'1h','context_interval':'1d','horizon_hours':HORIZON,'costs':{'fee_per_side':FEE,'slippage_per_side':SLIP},'production_changed':False,'results':result}
    open('backtest_v7_2_oos_results.json','w').write(json.dumps(out,indent=2)); print(json.dumps(out,indent=2))
if __name__=='__main__': main()
