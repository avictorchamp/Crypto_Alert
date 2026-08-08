import asyncio
from datetime import datetime, timezone

from app.crypto.price import get_market
from app.crypto.analyzer import analyze
from app.telegram.bot import send_message

SCAN_INTERVAL_SECONDS = 300

_last_signals = {}
_last_scan = None
_scheduler_task = None
_scan_lock = asyncio.Lock()


def _build_message(result):
    entry = result["entry"]
    tp = result["take_profit"]

    return f"""🚨 Crypto Alert V2.4

Coin: {result['coin']}/USDT
Signal: {result['signal']}
Confidence: {result['confidence']}%

Price: {result['price']}
RSI: {result['rsi']}

Entry: {entry['low']} - {entry['high']}
Stop Loss: {result['stop_loss']}
TP1: {tp['tp1']}
TP2: {tp['tp2']}
Risk/Reward: {result['risk_reward'] if result['risk_reward'] is not None else 'N/A'}

Support: {result['support']}
Resistance: {result['resistance']}

Reason: {', '.join(result['reason'])}
""".strip()


async def scan_once():
    global _last_scan

    async with _scan_lock:
        market = get_market()
        results = []

        for coin, data in market.items():
            result = analyze(coin, data)
            results.append(result)

            signal = result["signal"]
            previous = _last_signals.get(coin)

            # Alert only when a BUY setup appears or changes.
            should_alert = (
                signal in ("BUY SETUP", "STRONG BUY")
                and signal != previous
            )

            if should_alert:
                send_message(_build_message(result))

            _last_signals[coin] = signal

        _last_scan = datetime.now(timezone.utc).isoformat()
        return results


async def scheduler_loop():
    while True:
        try:
            await scan_once()
        except Exception as exc:
            print(f"[scheduler] scan error: {exc}")

        await asyncio.sleep(SCAN_INTERVAL_SECONDS)


def start_scheduler():
    global _scheduler_task

    if _scheduler_task is None or _scheduler_task.done():
        _scheduler_task = asyncio.create_task(scheduler_loop())

    return _scheduler_task


def scheduler_status():
    return {
        "running": _scheduler_task is not None and not _scheduler_task.done(),
        "interval_seconds": SCAN_INTERVAL_SECONDS,
        "last_scan": _last_scan,
        "signals": dict(_last_signals),
    }
