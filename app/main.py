from fastapi import FastAPI

from app.crypto.price import get_market
from app.crypto.analyzer import analyze
from app.telegram.bot import send_message
from app.config import VERSION

import threading
import time


app = FastAPI(
    title="Crypto Alert",
    version=VERSION
)


# =========================================================
# V2.5.6
# PRODUCTION CLEANUP
# =========================================================

SCAN_INTERVAL = 300       # 5 minutes
ALERT_COOLDOWN = 1800     # 30 minutes

ALERT_SIGNALS = {
    "BUY SETUP",
    "STRONG BUY",
    "SELL WATCH"
}


# =========================================================
# ALERT STATE
# =========================================================

last_signal = {}

last_sent_signal = {}

last_alert_time = {}

state_lock = threading.Lock()


# =========================================================
# ROOT
# =========================================================

@app.get("/")
def root():

    return {
        "service": "Crypto Alert",
        "version": VERSION,
        "status": "running"
    }


# =========================================================
# ALERT PROCESSOR
# =========================================================

def process_alert(coin, price, result):

    signal = result.get(
        "signal",
        "WAIT"
    )

    now = time.time()

    # -----------------------------------------------------
    # Read previous state
    # -----------------------------------------------------

    with state_lock:

        previous_signal = last_signal.get(
            coin
        )

        previous_sent = last_sent_signal.get(
            coin
        )

        previous_alert_time = last_alert_time.get(
            coin,
            0
        )

        last_signal[coin] = signal

    # -----------------------------------------------------
    # Non-alert signal
    #
    # Reset Telegram state when signal becomes WAIT
    # or another non-alertable signal.
    # -----------------------------------------------------

    if signal not in ALERT_SIGNALS:

        with state_lock:

            last_sent_signal.pop(
                coin,
                None
            )

            last_alert_time.pop(
                coin,
                None
            )

        return {
            "sent": False,
            "reason": "Signal not alertable"
        }

    # -----------------------------------------------------
    # Duplicate protection
    # -----------------------------------------------------

    if previous_sent == signal:

        elapsed = (
            now - previous_alert_time
        )

        if elapsed < ALERT_COOLDOWN:

            return {
                "sent": False,
                "reason": "Duplicate signal cooldown",
                "cooldown_remaining": round(
                    ALERT_COOLDOWN - elapsed,
                    1
                )
            }

    # -----------------------------------------------------
    # Message data
    # -----------------------------------------------------

    reasons = result.get(
        "reason",
        []
    )

    reason_text = (
        ", ".join(reasons)
        if reasons
        else "N/A"
    )

    entry = result.get(
        "entry",
        {}
    )

    take_profit = result.get(
        "take_profit",
        {}
    )

    message = f"""
🚨 Crypto Alert

Coin: {coin}/USDT

Signal:
{signal}

Price:
{price}

Confidence:
{result.get("confidence")}

Quality:
{result.get("quality_score")}
({result.get("quality_grade")})

Reason:
{reason_text}

Entry:
{entry.get("low")} - {entry.get("high")}

Stop Loss:
{result.get("stop_loss")}

Take Profit 1:
{take_profit.get("tp1")}

Take Profit 2:
{take_profit.get("tp2")}

Risk / Reward:
{result.get("risk_reward")}
"""

    # -----------------------------------------------------
    # Send Telegram
    # -----------------------------------------------------

    try:

        send_message(
            message
        )

    except Exception as e:

        print(
            f"Telegram error for {coin}: {e}"
        )

        return {
            "sent": False,
            "reason": "Telegram error",
            "error": str(e)
        }

    # -----------------------------------------------------
    # Save successful alert state
    # -----------------------------------------------------

    with state_lock:

        last_sent_signal[coin] = signal

        last_alert_time[coin] = now

    # -----------------------------------------------------
    # Alert reason
    # -----------------------------------------------------

    if previous_sent == signal:

        reason = "Cooldown expired"

    elif previous_signal != signal:

        reason = "New signal"

    else:

        reason = "First alert"

    return {
        "sent": True,
        "reason": reason
    }


# =========================================================
# NORMAL SCAN
# =========================================================

@app.get("/scan")
def scan():

    market = get_market()

    alerts = []

    alerts_sent = []

    alert_status = {}

    for coin, price in market.items():

        result = analyze(
            coin,
            price
        )

        alerts.append(
            result
        )

        status = process_alert(
            coin,
            price,
            result
        )

        alert_status[coin] = status

        if status["sent"]:

            alerts_sent.append(
                coin
            )

    return {
        "status": "success",
        "version": VERSION,
        "data": alerts,
        "alerts_sent": alerts_sent,
        "alert_status": alert_status
    }


# =========================================================
# ALERT STATE
# =========================================================

@app.get("/alert-state")
def alert_state():

    with state_lock:

        return {
            "last_signal": dict(
                last_signal
            ),
            "last_sent_signal": dict(
                last_sent_signal
            ),
            "last_alert_time": dict(
                last_alert_time
            )
        }


# =========================================================
# BACKGROUND SCHEDULER
# =========================================================

def scheduler():

    print(
        f"Crypto Alert scheduler started: "
        f"every {SCAN_INTERVAL} seconds"
    )

    while True:

        try:

            scan()

        except Exception as e:

            print(
                f"Scheduler error: {e}"
            )

        time.sleep(
            SCAN_INTERVAL
        )


# =========================================================
# START
# =========================================================

@app.on_event("startup")
def startup_event():

    thread = threading.Thread(
        target=scheduler,
        daemon=True
    )

    thread.start()
