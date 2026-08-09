from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.crypto.price import get_market
from app.crypto.analyzer import analyze
from app.telegram.bot import send_message
from app.crypto.binance_account import get_portfolio

import threading
import time
from datetime import datetime, timezone


# =========================================================
# CRYPTO ALERT V3.1.0
# =========================================================

VERSION = "3.1.0"

SCAN_INTERVAL = 300
ALERT_COOLDOWN = 1800

MIN_QUALITY = 70
MIN_RISK_REWARD = 1.0

BUY_SIGNALS = {
    "BUY SETUP",
    "STRONG BUY"
}

SELL_SIGNALS = {
    "SELL WATCH"
}


app = FastAPI(
    title="Crypto Alert",
    version=VERSION
)


# =========================================================
# STATE
# =========================================================

last_signal = {}
last_alert_time = {}

scheduler_started_at = None
last_scan_started = None
last_scan_completed = None
last_scan_duration = None
last_scan_error = None

state_lock = threading.Lock()
scan_lock = threading.Lock()


# =========================================================
# TIME
# =========================================================

def utc_now():
    return datetime.now(
        timezone.utc
    ).isoformat()


# =========================================================
# TELEGRAM TEST
# =========================================================

@app.get("/test-alert")
def test_alert():

    message = """
🚨 CRYPTO ALERT TEST

━━━━━━━━━━━━━━━━━━
BTC/USDT
━━━━━━━━━━━━━━━━━━

📌 SIGNAL
BUY SETUP

💰 PRICE
65000.00

📊 CONFIDENCE
80

⭐ QUALITY
80 (B)

📈 MARKET
BULLISH

📉 RSI
50.00

🎯 ENTRY
64255.13 - 64576.41

🛑 STOP LOSS
63612.58

🎯 TP1
65292.32

🎯 TP2
66022.15

⚖️ RISK / REWARD
1.09

━━━━━━━━━━━━━━━━━━
⚠️ TEST ALERT ONLY

This is a Telegram connectivity test.
This is NOT a real trading signal.
No automatic trading is performed.
"""

    try:

        send_message(message)

        return {
            "status": "success",
            "test": True,
            "version": VERSION,
            "telegram": True,
            "message": "Test alert sent"
        }

    except Exception as e:

        print(
            f"Telegram test error: {e}"
        )

        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "test": True,
                "version": VERSION,
                "telegram": False,
                "message": str(e)
            }
        )


# =========================================================
# MARKET REGIME
# =========================================================

def get_market_regime(result):

    ema20 = result.get("ema20")
    ema50 = result.get("ema50")

    if ema20 is None or ema50 is None:
        return {
            "status": "UNKNOWN",
            "score": 0,
            "reason": "EMA data unavailable"
        }

    try:

        ema20 = float(ema20)
        ema50 = float(ema50)

    except (TypeError, ValueError):

        return {
            "status": "UNKNOWN",
            "score": 0,
            "reason": "Invalid EMA data"
        }

    if ema50 == 0:

        return {
            "status": "UNKNOWN",
            "score": 0,
            "reason": "Invalid EMA50"
        }

    difference = (
        (ema20 - ema50)
        / abs(ema50)
    ) * 100

    if abs(difference) < 0.05:

        return {
            "status": "NEUTRAL",
            "score": 50,
            "reason": "EMA20 and EMA50 are close"
        }

    score = min(
        100,
        round(
            50 + abs(difference) * 100
        )
    )

    if difference > 0:

        return {
            "status": "BULLISH",
            "score": score,
            "reason": "EMA20 above EMA50"
        }

    return {
        "status": "BEARISH",
        "score": score,
        "reason": "EMA20 below EMA50"
    }


# =========================================================
# TRADE STATUS
# =========================================================

def get_trade_status(result):

    signal = result.get(
        "signal",
        "WAIT"
    )

    price = result.get("price")

    entry = result.get(
        "entry",
        {}
    )

    entry_low = entry.get("low")
    entry_high = entry.get("high")

    quality = result.get(
        "quality_score"
    )

    rsi = result.get("rsi")

    risk_reward = result.get(
        "risk_reward"
    )

    # -----------------------------------------------------
    # QUALITY
    # -----------------------------------------------------

    if quality is not None:

        try:

            if float(quality) < MIN_QUALITY:

                return {
                    "status": "LOW_QUALITY",
                    "action": "AVOID",
                    "reason": "Quality below minimum"
                }

        except (TypeError, ValueError):

            return {
                "status": "LOW_QUALITY",
                "action": "AVOID",
                "reason": "Invalid quality score"
            }

    # -----------------------------------------------------
    # RSI PROTECTION
    # -----------------------------------------------------

    if rsi is not None:

        try:

            rsi = float(rsi)

            if signal in BUY_SIGNALS and rsi >= 75:

                return {
                    "status": "RSI_OVERBOUGHT",
                    "action": "WAIT",
                    "reason": "RSI too high for BUY"
                }

            if signal in SELL_SIGNALS and rsi <= 25:

                return {
                    "status": "RSI_OVERSOLD",
                    "action": "WAIT",
                    "reason": "RSI too low for SELL"
                }

        except (TypeError, ValueError):

            pass

    # -----------------------------------------------------
    # RISK / REWARD
    # -----------------------------------------------------

    if risk_reward is not None:

        try:

            if float(risk_reward) < MIN_RISK_REWARD:

                return {
                    "status": "LOW_RISK_REWARD",
                    "action": "AVOID",
                    "reason": "Risk/reward below minimum"
                }

        except (TypeError, ValueError):

            pass

    # -----------------------------------------------------
    # ENTRY ZONE
    # -----------------------------------------------------

    if (
        price is not None
        and entry_low is not None
        and entry_high is not None
    ):

        try:

            price = float(price)
            entry_low = float(entry_low)
            entry_high = float(entry_high)

            if price < entry_low:

                return {
                    "status": "BELOW_ENTRY",
                    "action": "WAIT_FOR_ENTRY",
                    "reason": "Price below entry zone"
                }

            if price > entry_high:

                return {
                    "status": "ABOVE_ENTRY",
                    "action": "WAIT_FOR_ENTRY",
                    "reason": "Price above entry zone"
                }

            return {
                "status": "IN_ENTRY",
                "action": "READY",
                "reason": "Price inside entry zone"
            }

        except (TypeError, ValueError):

            pass

    # -----------------------------------------------------
    # DEFAULT
    # -----------------------------------------------------

    if signal in BUY_SIGNALS:

        return {
            "status": "SETUP",
            "action": "WAIT",
            "reason": "Waiting for valid entry"
        }

    if signal in SELL_SIGNALS:

        return {
            "status": "SETUP",
            "action": "WAIT",
            "reason": "Waiting for valid entry"
        }

    return {
        "status": "WAIT",
        "action": "WAIT",
        "reason": "No actionable signal"
    }


# =========================================================
# ALERT DECISION
# =========================================================

def evaluate_alert(
    result,
    regime,
    trade
):

    signal = result.get(
        "signal",
        "WAIT"
    )

    quality = result.get(
        "quality_score"
    )

    rr = result.get(
        "risk_reward"
    )

    # -----------------------------------------------------
    # SIGNAL
    # -----------------------------------------------------

    if signal not in (
        BUY_SIGNALS | SELL_SIGNALS
    ):

        return {
            "allowed": False,
            "reason": "Signal not alertable"
        }

    # -----------------------------------------------------
    # QUALITY
    # -----------------------------------------------------

    if quality is None:

        return {
            "allowed": False,
            "reason": "Quality score unavailable"
        }

    try:

        if float(quality) < MIN_QUALITY:

            return {
                "allowed": False,
                "reason": "Quality below alert threshold"
            }

    except (TypeError, ValueError):

        return {
            "allowed": False,
            "reason": "Invalid quality score"
        }

    # -----------------------------------------------------
    # RISK / REWARD
    # -----------------------------------------------------

    if rr is None:

        return {
            "allowed": False,
            "reason": "Risk/reward unavailable"
        }

    try:

        if float(rr) < MIN_RISK_REWARD:

            return {
                "allowed": False,
                "reason": "Risk/reward below threshold"
            }

    except (TypeError, ValueError):

        return {
            "allowed": False,
            "reason": "Invalid risk/reward"
        }

    # -----------------------------------------------------
    # MARKET REGIME
    # -----------------------------------------------------

    if signal in BUY_SIGNALS:

        if regime["status"] != "BULLISH":

            return {
                "allowed": False,
                "reason": "BUY blocked by market regime",
                "regime": regime["status"]
            }

    if signal in SELL_SIGNALS:

        if regime["status"] != "BEARISH":

            return {
                "allowed": False,
                "reason": "SELL blocked by market regime",
                "regime": regime["status"]
            }

    # -----------------------------------------------------
    # ENTRY ZONE
    # -----------------------------------------------------

    if trade["status"] != "IN_ENTRY":

        return {
            "allowed": False,
            "reason": "Price is not inside entry zone",
            "trade_status": trade["status"]
        }

    return {
        "allowed": True,
        "reason": "All alert conditions passed"
    }


# =========================================================
# SEND REAL ALERT
# =========================================================

def send_alert(
    coin,
    price,
    result,
    regime,
    trade
):

    signal = result.get("signal")

    quality = result.get(
        "quality_score"
    )

    grade = result.get(
        "quality_grade"
    )

    confidence = result.get(
        "confidence"
    )

    rsi = result.get(
        "rsi"
    )

    entry = result.get(
        "entry",
        {}
    )

    stop_loss = result.get(
        "stop_loss"
    )

    take_profit = result.get(
        "take_profit",
        {}
    )

    rr = result.get(
        "risk_reward"
    )

    reasons = result.get(
        "reason",
        []
    )

    reason_text = (
        "\n".join(
            f"• {reason}"
            for reason in reasons
        )
        if reasons
        else "• N/A"
    )

    # -----------------------------------------------------
    # FORMAT PRICE
    # -----------------------------------------------------

    try:
        price_text = f"{float(price):,.4f}"
    except:
        price_text = str(price)

    try:
        entry_low_text = f"{float(entry.get('low')):,.4f}"
    except:
        entry_low_text = str(entry.get("low"))

    try:
        entry_high_text = f"{float(entry.get('high')):,.4f}"
    except:
        entry_high_text = str(entry.get("high"))

    try:
        sl_text = f"{float(stop_loss):,.4f}"
    except:
        sl_text = str(stop_loss)

    try:
        tp1_text = f"{float(take_profit.get('tp1')):,.4f}"
    except:
        tp1_text = str(take_profit.get("tp1"))

    try:
        tp2_text = f"{float(take_profit.get('tp2')):,.4f}"
    except:
        tp2_text = str(take_profit.get("tp2"))

    message = f"""
🚨 CRYPTO ALERT

━━━━━━━━━━━━━━━━━━
{coin}/USDT
━━━━━━━━━━━━━━━━━━

📌 SIGNAL
{signal}

💰 PRICE
{price_text}

📊 CONFIDENCE
{confidence}%

⭐ QUALITY
{quality} ({grade})

📈 MARKET REGIME
{regime["status"]}

📉 RSI
{rsi}

🎯 ENTRY ZONE
{entry_low_text} - {entry_high_text}

🛑 STOP LOSS
{sl_text}

🎯 TAKE PROFIT 1
{tp1_text}

🎯 TAKE PROFIT 2
{tp2_text}

⚖️ RISK / REWARD
{rr}

🧠 REASON
{reason_text}

✅ TRADE STATUS
{trade["status"]}

━━━━━━━━━━━━━━━━━━

⚠️ Manual execution only.
No automatic trading.
"""

    send_message(message)


# =========================================================
# PROCESS ALERT
# =========================================================

def process_alert(
    coin,
    price,
    result
):

    regime = get_market_regime(
        result
    )

    trade = get_trade_status(
        result
    )

    decision = evaluate_alert(
        result,
        regime,
        trade
    )

    signal = result.get(
        "signal",
        "WAIT"
    )

    # -----------------------------------------------------
    # IMPORTANT:
    # Only actionable signals are allowed to create
    # alert state.
    #
    # WAIT / ABOVE_ENTRY / LOW_QUALITY do NOT overwrite
    # the previous successful alert state.
    # -----------------------------------------------------

    if not decision["allowed"]:

        return {
            "sent": False,
            "reason": decision["reason"],
            "market_regime": regime["status"],
            "trade_status": trade["status"],
            "trade_action": trade["action"]
        }

    now = time.time()

    with state_lock:

        previous_signal = last_signal.get(
            coin
        )

        previous_alert_time = last_alert_time.get(
            coin,
            0
        )

    # -----------------------------------------------------
    # DUPLICATE SIGNAL COOLDOWN
    # -----------------------------------------------------

    if previous_signal == signal:

        elapsed = (
            now - previous_alert_time
        )

        if elapsed < ALERT_COOLDOWN:

            return {
                "sent": False,
                "reason": "Duplicate signal cooldown",
                "cooldown_remaining":
                    round(
                        ALERT_COOLDOWN - elapsed,
                        1
                    ),
                "market_regime": regime["status"],
                "trade_status": trade["status"],
                "trade_action": trade["action"]
            }

    # -----------------------------------------------------
    # SEND TELEGRAM
    # -----------------------------------------------------

    try:

        send_alert(
            coin,
            price,
            result,
            regime,
            trade
        )

    except Exception as e:

        print(
            f"Telegram error for {coin}: {e}"
        )

        return {
            "sent": False,
            "reason": "Telegram error",
            "error": str(e),
            "market_regime": regime["status"],
            "trade_status": trade["status"]
        }

    # -----------------------------------------------------
    # SAVE ONLY SUCCESSFUL ALERT STATE
    # -----------------------------------------------------

    with state_lock:

        last_signal[coin] = signal
        last_alert_time[coin] = now

    return {
        "sent": True,
        "reason": "New signal",
        "market_regime": regime["status"],
        "trade_status": trade["status"],
        "trade_action": trade["action"]
    }


# =========================================================
# ENRICH RESULT
# =========================================================

def enrich_result(result):

    regime = get_market_regime(
        result
    )

    trade = get_trade_status(
        result
    )

    result["market_regime"] = {
        "status": regime["status"],
        "score": regime["score"],
        "reason": regime["reason"]
    }

    result["trade_status"] = (
        trade["status"]
    )

    result["trade_action"] = (
        trade["action"]
    )

    return result


# =========================================================
# SCAN
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

        data = []
        alerts_sent = []
        alert_status = {}

        for coin, price in market.items():

            result = analyze(
                coin,
                price
            )

            result = enrich_result(
                result
            )

            data.append(
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

        last_scan_completed = utc_now()

        last_scan_duration = round(
            time.time() - started,
            3
        )

        last_scan_error = None

        return {
            "status": "success",
            "version": VERSION,
            "data": data,
            "alerts_sent": alerts_sent,
            "alert_status": alert_status
        }

    except Exception as e:

        last_scan_completed = utc_now()

        last_scan_duration = round(
            time.time() - started,
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

    return {
        "status": "healthy",
        "service": "Crypto Alert",
        "version": VERSION,
        "rules": {
            "minimum_quality": MIN_QUALITY,
            "minimum_risk_reward": MIN_RISK_REWARD,
            "alert_cooldown_seconds":
                ALERT_COOLDOWN,
            "scan_interval_seconds":
                SCAN_INTERVAL
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

    result = {}

    with state_lock:

        for coin in set(
            last_signal.keys()
        ):

            sent_time = last_alert_time.get(
                coin
            )

            cooldown = 0

            if sent_time:

                cooldown = max(
                    0,
                    round(
                        ALERT_COOLDOWN
                        - (now - sent_time),
                        1
                    )
                )

            result[coin] = {
                "last_signal":
                    last_signal.get(
                        coin
                    ),
                "cooldown_remaining":
                    cooldown
            }

    return {
        "status": "success",
        "version": VERSION,
        "states": result
    }

# =========================================================
# BINANCE PORTFOLIO
# =========================================================

@app.get("/portfolio")
def portfolio():

    try:

        result = get_portfolio()

        return {
            "status": "success",
            "version": VERSION,
            "source": "Binance",
            "account_mode": "READ_ONLY",
            "portfolio": result
        }

    except Exception as e:

        print(
            f"Portfolio error: {e}"
        )

        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "version": VERSION,
                "source": "Binance",
                "account_mode": "READ_ONLY",
                "message": str(e)
            }
        )



# =========================================================
# SCHEDULER
# =========================================================

def scheduler():

    global scheduler_started_at

    scheduler_started_at = utc_now()

    print(
        "Crypto Alert V3.1 scheduler started: "
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
                "another scan is running"
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
