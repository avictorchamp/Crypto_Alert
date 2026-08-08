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
# V2.5.5
# ALERT COOLDOWN + SIGNAL RECOVERY
# =========================================================

SCAN_INTERVAL = 300          # 5 minutes
ALERT_COOLDOWN = 1800        # 30 minutes

ALERT_SIGNALS = {
    "BUY SETUP",
    "STRONG BUY",
    "SELL WATCH"
}


# =========================================================
# STATE
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
    # Previous state
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
    # WAIT / non-alert signals
    # -----------------------------------------------------

    if signal not in ALERT_SIGNALS:

        return {
            "sent": False,
            "reason": "Signal not alertable"
        }

    # -----------------------------------------------------
    # Detect signal change
    # -----------------------------------------------------

    signal_changed = (
        previous_signal is not None
        and previous_signal != signal
    )

    # -----------------------------------------------------
    # Duplicate protection
    # -----------------------------------------------------

    if previous_sent == signal:

        # Same signal inside cooldown
        if (
            now - previous_alert_time
            < ALERT_COOLDOWN
        ):

            return {
                "sent": False,
                "reason": "Duplicate signal cooldown"
            }

        # Same signal after cooldown
        # Allow a fresh alert only if enough time passed.

    # -----------------------------------------------------
    # Build message
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
            "reason": "Telegram error"
        }

    # -----------------------------------------------------
    # Save successful alert state
    # -----------------------------------------------------

    with state_lock:

        last_sent_signal[coin] = signal

        last_alert_time[coin] = now

    if signal_changed:

        reason = "New signal"

    elif previous_sent == signal:

        reason = "Cooldown expired"

    else:

        reason = "First alert"

    return {
        "sent": True,
        "reason": reason
    }


# =========================================================
# SCAN
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
# BACKGROUND SCHEDULER
# =========================================================

def scheduler():

    print(
        f"Crypto Alert V2.5.5 scheduler started: "
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
# START SCHEDULER
# =========================================================

@app.on_event("startup")
def startup_event():

    thread = threading.Thread(
        target=scheduler,
        daemon=True
    )

    thread.start()
