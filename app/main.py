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
# V2.8.0
# MARKET OPPORTUNITY STATUS
# =========================================================

SCAN_INTERVAL = 300
ALERT_COOLDOWN = 1800

MIN_ALERT_QUALITY = 70

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
scan_lock = threading.Lock()

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
# MARKET OPPORTUNITY
# =========================================================

def determine_trade_status(result):

    signal = result.get(
        "signal",
        "WAIT"
    )

    quality_score = result.get(
        "quality_score"
    )

    rsi = result.get(
        "rsi"
    )

    price = result.get(
        "price"
    )

    entry = result.get(
        "entry",
        {}
    )

    entry_low = entry.get(
        "low"
    )

    entry_high = entry.get(
        "high"
    )

    # -----------------------------------------------------
    # Low quality
    # -----------------------------------------------------

    if (
        quality_score is not None
        and quality_score < MIN_ALERT_QUALITY
    ):

        return {
            "trade_status": "LOW_QUALITY",
            "trade_action": "AVOID"
        }

    # -----------------------------------------------------
    # RSI extreme
    # -----------------------------------------------------

    if rsi is not None:

        if rsi >= 80:

            return {
                "trade_status": "RSI_EXTREME",
                "trade_action": "WAIT_FOR_RSI"
            }

    # -----------------------------------------------------
    # Active BUY signal
    # -----------------------------------------------------

    if signal in {
        "BUY SETUP",
        "STRONG BUY"
    }:

        if (
            price is not None
            and entry_low is not None
            and entry_high is not None
        ):

            if price > entry_high:

                return {
                    "trade_status": "ABOVE_ENTRY",
                    "trade_action": "WAIT_FOR_ENTRY"
                }

            if (
                price >= entry_low
                and price <= entry_high
            ):

                return {
                    "trade_status": "IN_ENTRY",
                    "trade_action": "BUY_SETUP"
                }

        return {
            "trade_status": "GOOD_SETUP",
            "trade_action": "WAIT_FOR_ENTRY"
        }

    # -----------------------------------------------------
    # WAIT but price is above entry
    #
    # This is especially useful for cases such as:
    #
    # EMA Bullish
    # RSI Oversold
    # Price Above Entry Zone
    # -----------------------------------------------------

    if signal == "WAIT":

        if (
            price is not None
            and entry_high is not None
            and price > entry_high
        ):

            return {
                "trade_status": "ABOVE_ENTRY",
                "trade_action": "WAIT_FOR_ENTRY"
            }

        if (
            price is not None
            and entry_low is not None
            and entry_high is not None
            and price >= entry_low
            and price <= entry_high
        ):

            return {
                "trade_status": "IN_ENTRY",
                "trade_action": "WAIT_SIGNAL"
            }

        return {
            "trade_status": "WAIT",
            "trade_action": "WAIT"
        }

    # -----------------------------------------------------
    # Other signals
    # -----------------------------------------------------

    return {
        "trade_status": "WAIT",
        "trade_action": "WAIT"
    }


# =========================================================
# ENRICH ANALYSIS
# =========================================================

def enrich_result(result):

    opportunity = determine_trade_status(
        result
    )

    result["trade_status"] = opportunity[
        "trade_status"
    ]

    result["trade_action"] = opportunity[
        "trade_action"
    ]

    return result


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
            "alert_filter": {
                "minimum_quality":
                    MIN_ALERT_QUALITY
            },
            "scheduler": {
                "started_at":
                    scheduler_started_at,

                "last_scan":
                    last_scan_completed,

                "last_scan_duration_seconds":
                    last_scan_duration,

                "last_error":
                    last_scan_error
            }
        }


# =========================================================
# ALERT QUALITY
# =========================================================

def check_alert_quality(result):

    quality_score = result.get(
        "quality_score"
    )

    quality_grade = result.get(
        "quality_grade"
    )

    if quality_score is None:

        return {
            "allowed": False,
            "reason": "Quality score unavailable"
        }

    try:

        quality_score = float(
            quality_score
        )

    except (
        TypeError,
        ValueError
    ):

        return {
            "allowed": False,
            "reason": "Invalid quality score"
        }

    if quality_score < MIN_ALERT_QUALITY:

        return {
            "allowed": False,
            "reason":
                "Quality below alert threshold",
            "quality_score":
                quality_score,
            "minimum_required":
                MIN_ALERT_QUALITY,
            "quality_grade":
                quality_grade
        }

    return {
        "allowed": True,
        "reason":
            "Quality threshold passed",
        "quality_score":
            quality_score,
        "quality_grade":
            quality_grade
    }


# =========================================================
# ALERT PROCESSOR
# =========================================================

def process_alert(
    coin,
    price,
    result
):

    signal = result.get(
        "signal",
        "WAIT"
    )

    now = time.time()

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
    # Signal not alertable
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
            "reason":
                "Signal not alertable"
        }

    # -----------------------------------------------------
    # Quality filter
    # -----------------------------------------------------

    quality = check_alert_quality(
        result
    )

    if not quality["allowed"]:

        return {
            "sent": False,
            "reason":
                quality["reason"],
            "quality_score":
                quality.get(
                    "quality_score"
                ),
            "quality_grade":
                quality.get(
                    "quality_grade"
                ),
            "minimum_required":
                quality.get(
                    "minimum_required",
                    MIN_ALERT_QUALITY
                )
        }

    # -----------------------------------------------------
    # Duplicate / cooldown
    # -----------------------------------------------------

    if previous_sent == signal:

        elapsed = (
            now - previous_alert_time
        )

        if elapsed < ALERT_COOLDOWN:

            return {
                "sent": False,
                "reason":
                    "Duplicate signal cooldown",
                "cooldown_remaining":
                    round(
                        ALERT_COOLDOWN - elapsed,
                        1
                    )
            }

    # -----------------------------------------------------
    # Message
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

Trade Status:
{result.get("trade_status")}

Trade Action:
{result.get("trade_action")}

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

    with state_lock:

        last_sent_signal[coin] = signal
        last_alert_time[coin] = now

    if previous_sent == signal:

        reason = "Cooldown expired"

    elif previous_signal != signal:

        reason = "New signal"

    else:

        reason = "First alert"

    return {
        "sent": True,
        "reason": reason,
        "quality_score":
            result.get("quality_score"),
        "quality_grade":
            result.get("quality_grade"),
        "trade_status":
            result.get("trade_status"),
        "trade_action":
            result.get("trade_action")
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

            # -------------------------------------------------
            # Preserve original analyzer data
            # and add opportunity status.
            # -------------------------------------------------

            result = enrich_result(
                result
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
            "alerts_sent":
                alerts_sent,
            "alert_status":
                alert_status
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
# SCAN API
# =========================================================

@app.get("/scan")
def scan():

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
                    last_signal.get(
                        coin
                    ),

                "last_sent_signal":
                    last_sent_signal.get(
                        coin
                    ),

                "cooldown_remaining":
                    cooldown_remaining
            }

    return {
        "status": "success",
        "version": VERSION,
        "states": states
    }


# =========================================================
# SCHEDULER
# =========================================================

def scheduler():

    global scheduler_started_at

    scheduler_started_at = utc_now()

    print(
        "Crypto Alert V2.8 scheduler started: "
        f"every {SCAN_INTERVAL} seconds"
    )

    while True:

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
