from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.crypto.price import get_market
from app.crypto.analyzer import analyze
from app.telegram.bot import send_message
from app.config import VERSION

import threading
import time
from datetime import datetime, timezone


app = FastAPI(
    title="Crypto Alert",
    version=VERSION
)


# =========================================================
# V2.6.0
# PRODUCTION RELIABILITY
# =========================================================

SCAN_INTERVAL = 300       # 5 minutes
ALERT_COOLDOWN = 1800     # 30 minutes


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

# Prevent two scans from running at the same time
scan_lock = threading.Lock()

# Scheduler / scan status
scheduler_started_at = None
last_scan_started = None
last_scan_completed = None
last_scan_duration = None
last_scan_error = None


# =========================================================
# TIME
# =========================================================

def utc_now():

    return datetime.now(
        timezone.utc
    ).isoformat()


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
# HEALTH
# =========================================================

@app.get("/health")
def health():

    with state_lock:

        return {
            "status": "healthy",
            "service": "Crypto Alert",
            "version": VERSION,
            "scheduler": {
                "started_at": scheduler_started_at,
                "last_scan": last_scan_completed,
                "last_scan_duration_seconds":
                    last_scan_duration,
                "last_error":
                    last_scan_error
            }
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
    # Reset alert state so a future BUY/SELL signal
    # can generate a new Telegram alert.
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
    # Duplicate / cooldown protection
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
    # Telegram
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
    # Save successful alert
    # -----------------------------------------------------

    with state_lock:

        last_sent_signal[coin] = signal

        last_alert_time[coin] = now

    # -----------------------------------------------------
    # Reason
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
# SCAN ENGINE
# =========================================================

def execute_scan():

    global last_scan_started
    global last_scan_completed
    global last_scan_duration
    global last_scan_error

    started = time.time()

    last_scan_started = utc_now()

    try:

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

        completed = time.time()

        last_scan_completed = utc_now()

        last_scan_duration = round(
            completed - started,
            3
        )

        last_scan_error = None

        return {
            "status": "success",
            "version": VERSION,
            "data": alerts,
            "alerts_sent": alerts_sent,
            "alert_status": alert_status
        }

    except Exception as e:

        completed = time.time()

        last_scan_completed = utc_now()

        last_scan_duration = round(
            completed - started,
            3
        )

        last_scan_error = str(e)

        print(
            f"Scan error: {e}"
        )

        return {
            "status": "error",
            "version": VERSION,
            "message": str(e)
        }


# =========================================================
# NORMAL SCAN API
# =========================================================

@app.get("/scan")
def scan():

    # -----------------------------------------------------
    # Prevent overlapping scans
    # -----------------------------------------------------

    if not scan_lock.acquire(
        blocking=False
    ):

        return JSONResponse(
            status_code=409,
            content={
                "status": "busy",
                "version": VERSION,
                "message":
                    "A scan is already running"
            }
        )

    try:

        return execute_scan()

    finally:

        scan_lock.release()


# =========================================================
# ALERT STATE
# =========================================================

@app.get("/alert-state")
def alert_state():

    now = time.time()

    states = {}

    with state_lock:

        coins = set(
            list(last_signal.keys())
            + list(last_sent_signal.keys())
        )

        for coin in coins:

            sent_time = last_alert_time.get(
                coin
            )

            cooldown_remaining = 0

            if sent_time:

                elapsed = (
                    now - sent_time
                )

                cooldown_remaining = max(
                    0,
                    round(
                        ALERT_COOLDOWN - elapsed,
                        1
                    )
                )

            states[coin] = {
                "signal":
                    last_signal.get(coin),

                "last_sent_signal":
                    last_sent_signal.get(coin),

                "cooldown_remaining":
                    cooldown_remaining
            }

    return {
        "status": "success",
        "version": VERSION,
        "states": states
    }


# =========================================================
# BACKGROUND SCHEDULER
# =========================================================

def scheduler():

    global scheduler_started_at

    scheduler_started_at = utc_now()

    print(
        "Crypto Alert V2.6 scheduler started: "
        f"every {SCAN_INTERVAL} seconds"
    )

    while True:

        # -------------------------------------------------
        # Don't overlap with a manually requested /scan
        # -------------------------------------------------

        if scan_lock.acquire(
            blocking=False
        ):

            try:

                result = execute_scan()

                print(
                    "Scheduled scan:",
                    result.get("status")
                )

            except Exception as e:

                print(
                    f"Scheduler error: {e}"
                )

            finally:

                scan_lock.release()

        else:

            print(
                "Scheduled scan skipped: "
                "another scan is already running"
            )

        time.sleep(
            SCAN_INTERVAL
        )


# =========================================================
# STARTUP
# =========================================================

@app.on_event("startup")
def startup_event():

    thread = threading.Thread(
        target=scheduler,
        daemon=True
    )

    thread.start()
