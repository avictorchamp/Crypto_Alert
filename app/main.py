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
# V2.5.3 SMART ALERT
# =========================================================

SCAN_INTERVAL = 300  # 5 minutes

# Store the last signal sent for each coin
last_sent_signal = {}

# Lock to protect alert state
alert_lock = threading.Lock()


# =========================================================
# SIGNALS THAT ARE ALLOWED TO SEND TELEGRAM
# =========================================================

ALERT_SIGNALS = {
    "BUY SETUP",
    "STRONG BUY",
    "SELL WATCH"
}


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
# SEND ALERT
# =========================================================

def send_alert(coin, price, result):

    signal = result["signal"]

    # -----------------------------------------------------
    # WAIT = no Telegram alert
    # -----------------------------------------------------

    if signal not in ALERT_SIGNALS:

        return False

    # -----------------------------------------------------
    # Duplicate protection
    # -----------------------------------------------------

    with alert_lock:

        previous_signal = last_sent_signal.get(
            coin
        )

        if previous_signal == signal:

            return False

        last_sent_signal[coin] = signal

    # -----------------------------------------------------
    # Build message
    # -----------------------------------------------------

    message = f"""
🚨 Crypto Alert

Coin: {coin}/USDT

Price:
{price}

Signal:
{signal}

Confidence:
{result.get("confidence")}

Quality:
{result.get("quality_score")} ({result.get("quality_grade")})

Reason:
{", ".join(result.get("reason", []))}

Entry:
{result["entry"]["low"]} - {result["entry"]["high"]}

Stop Loss:
{result["stop_loss"]}

Take Profit 1:
{result["take_profit"]["tp1"]}

Take Profit 2:
{result["take_profit"]["tp2"]}

Risk / Reward:
{result.get("risk_reward")}
"""

    try:

        send_message(message)

        return True

    except Exception as e:

        # If Telegram fails, don't permanently mark
        # the signal as successfully sent.

        with alert_lock:

            if last_sent_signal.get(coin) == signal:

                del last_sent_signal[coin]

        print(
            f"Telegram error for {coin}: {e}"
        )

        return False


# =========================================================
# SCAN
# =========================================================

@app.get("/scan")
def scan():

    market = get_market()

    alerts = []

    sent_alerts = []

    for coin, price in market.items():

        result = analyze(
            coin,
            price
        )

        alerts.append(
            result
        )

        # -------------------------------------------------
        # Smart Telegram Alert
        # -------------------------------------------------

        sent = send_alert(
            coin,
            price,
            result
        )

        if sent:

            sent_alerts.append(
                coin
            )

    return {

        "status": "success",

        "version": VERSION,

        "data": alerts,

        "alerts_sent": sent_alerts
    }


# =========================================================
# BACKGROUND SCHEDULER
# =========================================================

def scheduler():

    print(
        f"Crypto Alert V2.5.3 scheduler started: "
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
