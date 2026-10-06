#!/usr/bin/env python3
"""Export the exact XRP V7.15 feature edges used by the final gate."""
import json
from datetime import datetime,timedelta,timezone
from v7_6_coin_fingerprint import fetch,D,collect,learn_patterns
SYMBOL="XRPUSDT"; FORWARD_DAYS=90
def main():
 end=datetime.now(timezone.utc); freeze=end-timedelta(days=FORWARD_DAYS); start=freeze-timedelta(days=30.44*18+5)
 btc=fetch(D,"BTCUSDT",start,end); hist=collect(SYMBOL,start,freeze,btc)
 edges=learn_patterns(hist[:int(len(hist)*.20)])["edges"]
 out={"symbol":SYMBOL,"method":"V7.15 exact chronological 20% training quartile edges",
      "momentum_20":edges["momentum_20"],"vol_ratio":edges["vol_ratio"],
      "rule":{"momentum_20_bucket":0,"vol_ratio_bucket":3},"generated_at":end.isoformat()}
 open("v7_15_xrp_frozen_edges.json","w").write(json.dumps(out,indent=2)); print(json.dumps(out,indent=2))
if __name__=="__main__": main()
