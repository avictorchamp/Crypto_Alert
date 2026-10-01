"""V7.16 XRP alert-only production candidate.

Safety: emits alerts only. It never places orders or calls an exchange trading API.
The V7.15 validated rule remains XRPUSDT LONG / 48h.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

STATE_PATH = Path(os.getenv("CRYPTO_ALERT_STATE", "v7_16_alert_state.json"))
LOG_PATH = Path(os.getenv("CRYPTO_ALERT_LOG", "v7_16_alert_log.jsonl"))
COOLDOWN_SECONDS = int(os.getenv("XRP_ALERT_COOLDOWN_SECONDS", str(48 * 3600)))

RULE = {
    "version": "7.16.0-xrp-alert-production",
    "symbol": "XRPUSDT",
    "direction": "LONG",
    "horizon_hours": 48,
    "pattern": [["momentum_20", 0], ["vol_ratio", 3]],
    "source_gate": "V7.15 XRP Net Profit Final Gate",
    "mode": "ALERT_ONLY",
    "order_execution": False,
}


def _load_state() -> dict:
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True))


def _log(event: dict) -> None:
    with LOG_PATH.open("a") as f:
        f.write(json.dumps(event, sort_keys=True) + "\n")


def evaluate(features: dict) -> tuple[bool, str]:
    """Evaluate the validated V7.15 pattern using supplied market features."""
    try:
        momentum_20 = float(features["momentum_20"])
        vol_ratio = float(features["vol_ratio"])
    except (KeyError, TypeError, ValueError):
        return False, "missing_or_invalid_features"
    # V7.15 pattern bins: positive/non-negative momentum bucket and high-volume bucket.
    return momentum_20 >= 0 and vol_ratio >= 3, "rule_match" if momentum_20 >= 0 and vol_ratio >= 3 else "rule_no_match"


def run_once(features: dict, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    matched, reason = evaluate(features)
    state = _load_state()
    fingerprint = f"{RULE['symbol']}:{RULE['direction']}:{RULE['horizon_hours']}"
    last_sent = float(state.get(fingerprint, 0))
    cooldown_remaining = max(0, int(COOLDOWN_SECONDS - (now - last_sent))) if last_sent else 0
    emitted = bool(matched and cooldown_remaining == 0)

    event = {
        **RULE,
        "timestamp": datetime.fromtimestamp(now, timezone.utc).isoformat(),
        "matched": matched,
        "reason": reason,
        "emitted": emitted,
        "duplicate_suppressed": bool(matched and not emitted),
        "cooldown_seconds": COOLDOWN_SECONDS,
        "cooldown_remaining_seconds": cooldown_remaining,
        "features": features,
    }
    if emitted:
        state[fingerprint] = now
        _save_state(state)
        print("CRYPTO_ALERT", json.dumps(event, sort_keys=True))
    _log(event)
    return event


if __name__ == "__main__":
    # Market-feature producer can pass these values from the existing pipeline.
    features = {
        "momentum_20": os.getenv("XRP_MOMENTUM_20"),
        "vol_ratio": os.getenv("XRP_VOL_RATIO"),
    }
    result = run_once(features)
    print(json.dumps(result, indent=2, sort_keys=True))
