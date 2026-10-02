"""V7.16 XRP alert-only production candidate."""
from __future__ import annotations
import json, os, time
from datetime import datetime, timezone
from pathlib import Path
STATE_PATH=Path(os.getenv("CRYPTO_ALERT_STATE","v7_16_alert_state.json"))
LOG_PATH=Path(os.getenv("CRYPTO_ALERT_LOG","v7_16_alert_log.jsonl"))
COOLDOWN_SECONDS=int(os.getenv("XRP_ALERT_COOLDOWN_SECONDS",str(48*3600)))
RULE={"version":"7.16.0-xrp-alert-production","symbol":"XRPUSDT","direction":"LONG","horizon_hours":48,
"pattern":[["momentum_20",0],["vol_ratio",3]],"source_gate":"V7.15 XRP Net Profit Final Gate","mode":"ALERT_ONLY","order_execution":False}
def _load_state():
    if not STATE_PATH.exists(): return {}
    try: return json.loads(STATE_PATH.read_text())
    except (json.JSONDecodeError,OSError): return {}
def _save_state(s): STATE_PATH.write_text(json.dumps(s,indent=2,sort_keys=True))
def _log(e):
    with LOG_PATH.open("a") as f: f.write(json.dumps(e,sort_keys=True)+"\n")
def evaluate(features):
    try: m=float(features["momentum_20"]); v=float(features["vol_ratio"])
    except (KeyError,TypeError,ValueError): return False,"missing_or_invalid_features"
    ok=m>=0 and v>=3
    return ok,"rule_match" if ok else "rule_no_match"
def run_once(features,now=None):
    now=time.time() if now is None else now; matched,reason=evaluate(features); state=_load_state()
    fp=f"{RULE['symbol']}:{RULE['direction']}:{RULE['horizon_hours']}"; last=float(state.get(fp,0))
    remain=max(0,int(COOLDOWN_SECONDS-(now-last))) if last else 0; emitted=bool(matched and remain==0)
    event={**RULE,"timestamp":datetime.fromtimestamp(now,timezone.utc).isoformat(),"matched":matched,"reason":reason,
    "emitted":emitted,"duplicate_suppressed":bool(matched and not emitted),"cooldown_seconds":COOLDOWN_SECONDS,
    "cooldown_remaining_seconds":remain,"features":features}
    if emitted: state[fp]=now; _save_state(state); print("CRYPTO_ALERT",json.dumps(event,sort_keys=True))
    _log(event); return event
if __name__=="__main__":
    print(json.dumps(run_once({"momentum_20":os.getenv("XRP_MOMENTUM_20"),"vol_ratio":os.getenv("XRP_VOL_RATIO")}),indent=2,sort_keys=True))
