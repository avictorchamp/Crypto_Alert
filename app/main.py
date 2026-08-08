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
# V2.5.4
# ALERT STATE & DUPLICATE PROTECTION
# =========================================================

SCAN_INTERVAL = 300  # 5 minutes

ALERT_SIGNALS = {
    "BUY SETUP",
    "STRONG BUY",
    "SELL WATCH"
}


# =========================================================
# STATE
# =========================================================

# Last signal detected for each coin
last_signal = {}

# Last signal successfully sent to Telegram
last_sent_signal = {}

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
# SEND SMART ALERT
# =========================================================

def process_alert(coin, price, result):

    signal = result.get(
        "signal",
        "WAIT"
    )

    # -----------------------------------------------------
    # Update detected state
    # -----------------------------------------------------

    with state_lock:

        previous_signal = last_signal.get(
            coin
        )

        last_signal[coin] = signal

    # -----------------------------------------------------
    # WAIT does not generate Telegram alert
    # -----------------------------------------------------

    if signal not in ALERT_SIGNALS:

        return {
            "sent": False,
            "reason": "Signal not alertable"
        }

    # -----------------------------------------------------
    # Duplicate protection
    # -----------------------------------------------------

    with state_lock:

        previous_sent = last_sent_signal.get(
            coin
        )

        if previous_sent == signal:

            return {
                "sent": False,
                "reason": "Duplicate signal"
            }

    # -----------------------------------------------------
    # Build Telegram message
    # -----------------------------------------------------

    reasons = result.get(
        "reason",
        []
    )

    reason_text = ", ".join(
        reasons
    ) if reasons else "N/A"

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
    # Mark as successfully sent
    # -----------------------------------------------------

    with state_lock:

        last_sent_signal[coin] = signal

    return {
        "sent": True,
        "reason": "New alert"
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

        # -------------------------------------------------
        # Process Telegram alert
        # -------------------------------------------------

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
        f"Crypto Alert V2.5.4 scheduler started: "
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
