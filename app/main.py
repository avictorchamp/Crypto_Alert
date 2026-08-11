from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.crypto.price import get_market
from app.crypto.analyzer import analyze
from app.telegram.bot import send_message

from app.crypto.binance_account import get_portfolio
from app.crypto.binance_position import get_positions

from app.crypto.portfolio_monitor import run_portfolio_monitor
from app.crypto.portfolio_alert import monitor_portfolio_alerts
from app.crypto.watchlist_manager import (
    update_watchlist_memory,
    get_watchlist_details,
    get_watchlist_summary,
)

import threading
import time
from datetime import datetime, timezone


# =========================================================
# CRYPTO ALERT
# Version 3.9.0
#
# DESIGN
# 1. Dynamic Top 50 market scanner
# 2. Watchlist memory
#    - normal coins: 12 hours
#    - strong setups: 24 hours
# 3. Portfolio coins stay monitored while held
# 4. Portfolio monitor is READ ONLY
# 5. Telegram alerts
# 6. Scheduler every 5 minutes
# 7. NO automatic trading
#
# IMPORTANT:
# This file is a complete replacement for app/main.py.
# Do not insert snippets manually.
# =========================================================


VERSION = "3.9.0"

SCAN_INTERVAL = 300

ALERT_COOLDOWN = 1800

MIN_QUALITY = 70

MIN_RISK_REWARD = 1.0


BUY_SIGNALS = {
    "BUY SETUP",
    "STRONG BUY",
}

SELL_SIGNALS = {
    "SELL WATCH",
    "STRONG SELL",
}


# =========================================================
# APP
# =========================================================

app = FastAPI(
    title="Crypto Alert",
    version=VERSION,
)


# =========================================================
# GLOBAL STATE
# =========================================================

last_signal = {}
last_alert_time = {}

scheduler_started_at = None

last_scan_started = None
last_scan_completed = None
last_scan_duration = None
last_scan_error = None

last_watchlist_result = []
last_portfolio_result = []
last_portfolio_alert_result = {}

last_watchlist_memory = {}

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
# SAFE FLOAT
# =========================================================

def to_float(
    value,
    default=None,
):
    try:
        return float(value)
    except (
        TypeError,
        ValueError,
    ):
        return default


# =========================================================
# FORMAT
# =========================================================

def fmt(
    value,
    digits=4,
):
    number = to_float(value)

    if number is None:
        return "N/A"

    return f"{number:,.{digits}f}"


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
80%

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
            "message": "Test alert sent",
        }

    except Exception as e:

        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "test": True,
                "version": VERSION,
                "telegram": False,
                "message": str(e),
            },
        )


# =========================================================
# MARKET REGIME
# =========================================================

def get_market_regime(result):

    ema20 = to_float(
        result.get("ema20")
    )

    ema50 = to_float(
        result.get("ema50")
    )

    if (
        ema20 is None
        or ema50 is None
    ):
        return {
            "status": "UNKNOWN",
            "score": 0,
            "reason": "EMA data unavailable",
        }

    if ema50 == 0:
        return {
            "status": "UNKNOWN",
            "score": 0,
            "reason": "Invalid EMA50",
        }

    difference = (
        (ema20 - ema50)
        / abs(ema50)
    ) * 100

    if abs(difference) < 0.05:
        return {
            "status": "NEUTRAL",
            "score": 50,
            "reason": "EMA20 and EMA50 are close",
        }

    strength = min(
        50,
        abs(difference) * 100,
    )

    score = round(
        50 + strength
    )

    if difference > 0:
        return {
            "status": "BULLISH",
            "score": score,
            "reason": "EMA20 above EMA50",
        }

    return {
        "status": "BEARISH",
        "score": score,
        "reason": "EMA20 below EMA50",
    }


# =========================================================
# TRADE STATUS
# =========================================================

def get_trade_status(result):

    price = to_float(
        result.get("price")
    )

    entry = result.get(
        "entry",
        {},
    ) or {}

    entry_low = to_float(
        entry.get("low")
    )

    entry_high = to_float(
        entry.get("high")
    )

    quality = to_float(
        result.get("quality_score")
    )

    rsi = to_float(
        result.get("rsi")
    )

    risk_reward = to_float(
        result.get("risk_reward")
    )

    signal = result.get(
        "signal",
        "WAIT",
    )

    if (
        quality is not None
        and quality < MIN_QUALITY
    ):
        return {
            "status": "LOW_QUALITY",
            "action": "AVOID",
            "reason": "Quality below minimum",
        }

    if rsi is not None:

        if (
            signal in BUY_SIGNALS
            and rsi >= 75
        ):
            return {
                "status": "RSI_OVERBOUGHT",
                "action": "WAIT",
                "reason": "RSI too high for BUY",
            }

        if (
            signal in SELL_SIGNALS
            and rsi <= 25
        ):
            return {
                "status": "RSI_OVERSOLD",
                "action": "WAIT",
                "reason": "RSI too low for SELL",
            }

    if (
        risk_reward is not None
        and risk_reward < MIN_RISK_REWARD
    ):
        return {
            "status": "LOW_RISK_REWARD",
            "action": "AVOID",
            "reason": "Risk/reward below minimum",
        }

    if (
        price is not None
        and entry_low is not None
        and entry_high is not None
    ):

        if price < entry_low:
            return {
                "status": "BELOW_ENTRY",
                "action": "WAIT_FOR_ENTRY",
                "reason": "Price below entry zone",
            }

        if price > entry_high:
            return {
                "status": "ABOVE_ENTRY",
                "action": "WAIT_FOR_ENTRY",
                "reason": "Price above entry zone",
            }

        return {
            "status": "IN_ENTRY",
            "action": "READY",
            "reason": "Price inside entry zone",
        }

    return {
        "status": "WAIT",
        "action": "WAIT",
        "reason": "No actionable signal",
    }


# =========================================================
# ALERT DECISION
# =========================================================

def evaluate_watchlist_alert(
    result,
    regime,
    trade,
):

    signal = result.get(
        "signal",
        "WAIT",
    )

    quality = to_float(
        result.get("quality_score")
    )

    risk_reward = to_float(
        result.get("risk_reward")
    )

    if signal not in (
        BUY_SIGNALS
        | SELL_SIGNALS
    ):
        return {
            "allowed": False,
            "reason": "Signal not alertable",
        }

    if quality is None:
        return {
            "allowed": False,
            "reason": "Quality unavailable",
        }

    if quality < MIN_QUALITY:
        return {
            "allowed": False,
            "reason": "Quality below threshold",
        }

    if risk_reward is None:
        return {
            "allowed": False,
            "reason": "Risk/reward unavailable",
        }

    if risk_reward < MIN_RISK_REWARD:
        return {
            "allowed": False,
            "reason": "Risk/reward below threshold",
        }

    if signal in BUY_SIGNALS:
        if regime["status"] != "BULLISH":
            return {
                "allowed": False,
                "reason": "BUY blocked by market regime",
            }

    if signal in SELL_SIGNALS:
        if regime["status"] != "BEARISH":
            return {
                "allowed": False,
                "reason": "SELL blocked by market regime",
            }

    if trade["status"] != "IN_ENTRY":
        return {
            "allowed": False,
            "reason": "Price not inside entry zone",
        }

    return {
        "allowed": True,
        "reason": "All conditions passed",
    }


# =========================================================
# SEND WATCHLIST ALERT
# =========================================================

def send_watchlist_alert(
    coin,
    result,
    regime,
):

    signal = result.get("signal")
    quality = result.get("quality_score")
    grade = result.get("quality_grade")
    confidence = result.get("confidence")
    rsi = result.get("rsi")
    price = result.get("price")

    entry = result.get(
        "entry",
        {},
    ) or {}

    stop_loss = result.get(
        "stop_loss"
    )

    take_profit = result.get(
        "take_profit",
        {},
    ) or {}

    risk_reward = result.get(
        "risk_reward"
    )

    reasons = result.get(
        "reason",
        []
    )

    reason_text = "\n".join(
        f"• {x}"
        for x in reasons
    )

    message = f"""
🟢 CRYPTO ALERT

━━━━━━━━━━━━━━━━━━
{coin}
━━━━━━━━━━━━━━━━━━

📌 SIGNAL
{signal}

💰 PRICE
{fmt(price)}

📊 CONFIDENCE
{confidence}%

⭐ QUALITY
{quality} ({grade})

📈 MARKET
{regime["status"]}

📉 RSI
{rsi}

🎯 ENTRY
{fmt(entry.get("low"))} - {fmt(entry.get("high"))}

🛑 STOP LOSS
{fmt(stop_loss)}

🎯 TP1
{fmt(take_profit.get("tp1"))}

🎯 TP2
{fmt(take_profit.get("tp2"))}

⚖️ RISK / REWARD
{risk_reward}

🧠 REASON
{reason_text}

━━━━━━━━━━━━━━━━━━

⚠️ MANUAL EXECUTION ONLY
No automatic trading.
"""

    send_message(message)


# =========================================================
# PROCESS ALERT
# =========================================================

def process_watchlist_alert(
    coin,
    result,
):

    regime = get_market_regime(result)
    trade = get_trade_status(result)

    decision = evaluate_watchlist_alert(
        result,
        regime,
        trade,
    )

    if not decision["allowed"]:
        return {
            "sent": False,
            "reason": decision["reason"],
            "market_regime": regime["status"],
            "trade_status": trade["status"],
            "trade_action": trade["action"],
        }

    signal = result.get("signal")
    now = time.time()

    with state_lock:

        previous_signal = last_signal.get(
            coin
        )

        previous_time = last_alert_time.get(
            coin,
            0
        )

    if previous_signal == signal:

        elapsed = now - previous_time

        if elapsed < ALERT_COOLDOWN:

            return {
                "sent": False,
                "reason": "Duplicate signal cooldown",
                "cooldown_remaining": round(
                    ALERT_COOLDOWN - elapsed,
                    1,
                ),
                "market_regime": regime["status"],
                "trade_status": trade["status"],
                "trade_action": trade["action"],
            }

    try:

        send_watchlist_alert(
            coin,
            result,
            regime,
        )

    except Exception as e:

        return {
            "sent": False,
            "reason": f"Telegram error: {e}",
            "market_regime": regime["status"],
            "trade_status": trade["status"],
            "trade_action": trade["action"],
        }

    with state_lock:

        last_signal[coin] = signal
        last_alert_time[coin] = now

    return {
        "sent": True,
        "reason": "New signal",
        "market_regime": regime["status"],
        "trade_status": trade["status"],
        "trade_action": trade["action"],
    }


# =========================================================
# ANALYZE ONE ITEM
# =========================================================

def analyze_market_item(
    coin,
    item,
):

    try:

        try:
            result = analyze(item)

        except TypeError:
            result = analyze(
                coin,
                item,
            )

    except Exception as e:

        return {
            "coin": coin,
            "status": "ERROR",
            "error": str(e),
        }

    if result is None:
        return None

    result = dict(result)

    result.setdefault(
        "coin",
        coin,
    )

    regime = get_market_regime(
        result
    )

    trade = get_trade_status(
        result
    )

    result["market_regime"] = regime

    result["trade_status"] = trade["status"]

    result["trade_action"] = trade["action"]

    return result


# =========================================================
# WATCHLIST SCAN
# =========================================================

def run_watchlist_scan():

    global last_watchlist_memory

    market = get_market()

    if isinstance(market, dict):

        current_items = []

        for coin, data in market.items():

            if isinstance(data, dict):

                item = dict(data)

                item.setdefault(
                    "coin",
                    coin,
                )

                current_items.append(item)

    elif isinstance(market, list):

        current_items = market

    else:

        raise RuntimeError(
            "Unsupported get_market() response"
        )

    # -----------------------------------------------------
    # First pass:
    # remember current dynamic universe
    # -----------------------------------------------------

    memory = update_watchlist_memory(
        market_data=current_items,
        portfolio_response=None,
    )

    last_watchlist_memory = memory

    # -----------------------------------------------------
    # Analyze the current dynamic universe.
    #
    # The memory is maintained separately so coins that
    # leave Top 50 remain remembered. They will be included
    # in future scans once their market data is supplied.
    # -----------------------------------------------------

    results = []
    alerts_sent = []

    for item in current_items:

        if not isinstance(
            item,
            dict,
        ):
            continue

        coin = str(
            item.get(
                "coin",
                "",
            )
        ).upper()

        if not coin:
            continue

        result = analyze_market_item(
            coin,
            item,
        )

        if result is None:
            continue

        if result.get(
            "status"
        ) == "ERROR":

            results.append(result)
            continue

        alert = process_watchlist_alert(
            coin,
            result,
        )

        result["alert_status"] = alert

        results.append(result)

        if alert.get("sent"):
            alerts_sent.append(coin)

    return {
        "status": "success",
        "count": len(results),
        "dynamic_count": len(current_items),
        "alerts_sent": alerts_sent,
        "data": results,
        "watchlist_memory": memory,
    }


# =========================================================
# MARKET DATA MAP
# =========================================================

def build_market_data(
    watchlist_data,
):

    market_data = {}

    for item in watchlist_data:

        if not isinstance(
            item,
            dict,
        ):
            continue

        coin = str(
            item.get(
                "coin",
                "",
            )
        ).upper()

        if not coin:
            continue

        market_data[coin] = item

    return market_data


# =========================================================
# PORTFOLIO SCAN
# =========================================================

def run_portfolio_scan(
    watchlist_data,
):

    global last_portfolio_alert_result

    positions_response = get_positions()

    if not isinstance(
        positions_response,
        dict,
    ):
        positions_response = {
            "status": "success",
            "positions": [],
        }

    positions = positions_response.get(
        "positions",
        []
    )

    if not isinstance(
        positions,
        list,
    ):
        positions = []

    # -----------------------------------------------------
    # Update watchlist memory with portfolio.
    # Held assets are permanent while held.
    # -----------------------------------------------------

    memory = update_watchlist_memory(
        market_data=watchlist_data,
        portfolio_response={
            "positions": positions,
        },
    )

    market_data = build_market_data(
        watchlist_data
    )

    portfolio_response = {
        "status": "success",
        "account_type": "READ_ONLY",
        "positions": positions,
    }

    monitored = run_portfolio_monitor(
        portfolio_response=portfolio_response,
        market_data=market_data,
        rules={
            "minimum_quality": MIN_QUALITY,
            "minimum_risk_reward": MIN_RISK_REWARD,
        },
    )

    if not isinstance(
        monitored,
        dict,
    ):
        monitored = {
            "status": "success",
            "positions": positions,
            "position_count": len(positions),
        }

    monitored_positions = monitored.get(
        "positions",
        []
    )

    if not isinstance(
        monitored_positions,
        list,
    ):
        monitored_positions = positions

    try:

        portfolio_alerts = monitor_portfolio_alerts(
            monitored_positions
        )

    except Exception as e:

        portfolio_alerts = {
            "status": "error",
            "message": str(e),
            "alerts_sent": [],
            "results": [],
        }

    last_portfolio_alert_result = (
        portfolio_alerts
    )

    return {
        "status": monitored.get(
            "status",
            "success",
        ),
        "account_type": "READ_ONLY",
        "position_count": monitored.get(
            "position_count",
            len(monitored_positions),
        ),
        "high_priority_count": monitored.get(
            "high_priority_count",
            0,
        ),
        "positions": monitored_positions,
        "high_priority": monitored.get(
            "high_priority",
            [],
        ),
        "monitor_alerts": monitored.get(
            "alerts",
            [],
        ),
        "telegram_alerts": portfolio_alerts,
        "watchlist_memory": memory,
        "read_only": True,
    }


# =========================================================
# FULL SCAN
# =========================================================

def run_full_scan():

    global last_watchlist_result
    global last_portfolio_result

    errors = []

    try:

        watchlist = run_watchlist_scan()

    except Exception as e:

        errors.append(
            {
                "module": "watchlist",
                "error": str(e),
            }
        )

        watchlist = {
            "status": "error",
            "count": 0,
            "dynamic_count": 0,
            "alerts_sent": [],
            "data": [],
            "watchlist_memory": {},
            "error": str(e),
        }

    watchlist_data = watchlist.get(
        "data",
        []
    )

    last_watchlist_result = watchlist_data

    try:

        portfolio = run_portfolio_scan(
            watchlist_data
        )

    except Exception as e:

        errors.append(
            {
                "module": "portfolio",
                "error": str(e),
            }
        )

        portfolio = {
            "status": "error",
            "account_type": "READ_ONLY",
            "position_count": 0,
            "positions": [],
            "high_priority": [],
            "monitor_alerts": [],
            "telegram_alerts": {
                "status": "error",
                "message": str(e),
            },
            "watchlist_memory": {},
            "error": str(e),
        }

    last_portfolio_result = portfolio.get(
        "positions",
        []
    )

    # -----------------------------------------------------
    # Final memory snapshot
    # -----------------------------------------------------

    try:

        memory = update_watchlist_memory(
            market_data=watchlist_data,
            portfolio_response={
                "positions":
                    last_portfolio_result,
            },
        )

    except Exception as e:

        memory = {
            "status": "error",
            "message": str(e),
        }

    return {
        "status": (
            "success"
            if not errors
            else "partial_success"
        ),
        "watchlist": watchlist,
        "portfolio": portfolio,
        "watchlist_memory": memory,
        "errors": errors,
    }


# =========================================================
# MANUAL SCAN
# =========================================================

@app.get("/scan")
def scan():

    global last_scan_started
    global last_scan_completed
    global last_scan_duration
    global last_scan_error

    if not scan_lock.acquire(
        blocking=False
    ):

        return JSONResponse(
            status_code=409,
            content={
                "status": "busy",
                "version": VERSION,
                "message":
                    "A scan is already running",
            },
        )

    started = time.time()

    last_scan_started = utc_now()
    last_scan_error = None

    try:

        result = run_full_scan()

        last_scan_completed = utc_now()

        last_scan_duration = round(
            time.time() - started,
            3,
        )

        return {
            "status": result["status"],
            "version": VERSION,
            "watchlist": result["watchlist"],
            "portfolio": result["portfolio"],
            "watchlist_memory":
                result["watchlist_memory"],
            "errors": result["errors"],
        }

    except Exception as e:

        last_scan_error = str(e)

        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "version": VERSION,
                "message": str(e),
            },
        )

    finally:

        last_scan_completed = utc_now()

        last_scan_duration = round(
            time.time() - started,
            3,
        )

        scan_lock.release()


# =========================================================
# PORTFOLIO
# =========================================================

@app.get("/portfolio")
def portfolio():

    try:

        result = get_portfolio()

        return {
            "status": "success",
            "version": VERSION,
            "source": "Binance TH",
            "account_mode": "READ_ONLY",
            "portfolio": result,
        }

    except Exception as e:

        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "version": VERSION,
                "source": "Binance TH",
                "account_mode": "READ_ONLY",
                "message": str(e),
            },
        )


# =========================================================
# POSITIONS
# =========================================================

@app.get("/positions")
def positions():

    try:

        result = get_positions()

        return {
            "status": "success",
            "version": VERSION,
            "source": "Binance TH",
            "account_mode": "READ_ONLY",
            "positions": result,
        }

    except Exception as e:

        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "version": VERSION,
                "source": "Binance TH",
                "account_mode": "READ_ONLY",
                "message": str(e),
            },
        )


# =========================================================
# PORTFOLIO MONITOR
# =========================================================

@app.get("/portfolio-monitor")
def portfolio_monitor():

    try:

        result = run_full_scan()

        return {
            "status": result["status"],
            "version": VERSION,
            "source": "Binance TH",
            "account_mode": "READ_ONLY",
            "portfolio_monitor":
                result["portfolio"],
            "watchlist_memory":
                result["watchlist_memory"],
        }

    except Exception as e:

        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "version": VERSION,
                "source": "Binance TH",
                "account_mode": "READ_ONLY",
                "stage": "portfolio_monitor",
                "message": str(e),
            },
        )


# =========================================================
# WATCHLIST
# =========================================================

@app.get("/watchlist")
def watchlist():

    try:

        summary = get_watchlist_summary()

        return {
            "status": "success",
            "version": VERSION,
            "watchlist": summary,
            "details": get_watchlist_details(),
        }

    except Exception as e:

        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "version": VERSION,
                "message": str(e),
            },
        )


# =========================================================
# PORTFOLIO ALERT TEST
# =========================================================

@app.get("/test-portfolio-alert")
def test_portfolio_alert():

    test_position = {
        "asset": "BTC",
        "symbol": "BTC/THB",
        "quantity": 0.01,
        "average_entry": 2000000,
        "current_price": 2250000,
        "unrealized_pnl_percent": 12.5,
        "unrealized_pnl": 2500,
        "market_value": 22500,
        "market_regime": {
            "status": "BULLISH",
        },
        "quality_score": 82,
        "quality_grade": "B",
    }

    try:

        result = monitor_portfolio_alerts(
            [test_position],
            force=True,
        )

        return {
            "status": "success",
            "version": VERSION,
            "test": True,
            "result": result,
            "message":
                "Portfolio test alert sent",
        }

    except Exception as e:

        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "version": VERSION,
                "test": True,
                "message": str(e),
            },
        )


# =========================================================
# STATUS
# =========================================================

@app.get("/status")
def status():

    try:
        memory_summary = get_watchlist_summary()
    except Exception:
        memory_summary = {}

    return {
        "status": "success",
        "version": VERSION,

        "watchlist_count":
            len(last_watchlist_result),

        "portfolio_position_count":
            len(last_portfolio_result),

        "portfolio_alert_status":
            last_portfolio_alert_result,

        "watchlist_memory":
            memory_summary,

        "last_scan_started":
            last_scan_started,

        "last_scan_completed":
            last_scan_completed,

        "last_scan_duration_seconds":
            last_scan_duration,

        "last_scan_error":
            last_scan_error,
    }


# =========================================================
# HEALTH
# =========================================================

@app.get("/health")
def health():

    try:
        memory = get_watchlist_summary()
        memory_status = "ACTIVE"
    except Exception as e:
        memory = {}
        memory_status = f"ERROR: {e}"

    return {
        "status": "healthy",
        "service": "Crypto Alert",
        "version": VERSION,

        "rules": {
            "minimum_quality":
                MIN_QUALITY,

            "minimum_risk_reward":
                MIN_RISK_REWARD,

            "alert_cooldown_seconds":
                ALERT_COOLDOWN,

            "scan_interval_seconds":
                SCAN_INTERVAL,
        },

        "watchlist_memory": {
            "status":
                memory_status,

            "count":
                memory.get(
                    "total",
                    0,
                ),

            "portfolio_count":
                len(
                    memory.get(
                        "portfolio",
                        [],
                    )
                ),

            "strong_setup_count":
                len(
                    memory.get(
                        "strong_setup",
                        [],
                    )
                ),
        },

        "scheduler": {
            "started_at":
                scheduler_started_at,

            "last_scan":
                last_scan_completed,

            "last_scan_duration_seconds":
                last_scan_duration,

            "last_error":
                last_scan_error,
        },

        "modules": {
            "watchlist":
                "ACTIVE",

            "watchlist_memory":
                memory_status,

            "portfolio_monitor":
                "ACTIVE",

            "portfolio_alert":
                "ACTIVE",

            "binance":
                "READ_ONLY",

            "telegram":
                "ACTIVE",

            "automatic_trading":
                "DISABLED",
        },
    }


# =========================================================
# SCHEDULER
# =========================================================

def scheduler_loop():

    global scheduler_started_at
    global last_scan_started
    global last_scan_completed
    global last_scan_duration
    global last_scan_error

    scheduler_started_at = utc_now()

    print(
        f"[Scheduler] started "
        f"version={VERSION} "
        f"interval={SCAN_INTERVAL}s"
    )

    while True:

        started = time.time()

        if scan_lock.acquire(
            blocking=False
        ):

            try:

                last_scan_started = utc_now()
                last_scan_error = None

                result = run_full_scan()

                last_scan_completed = utc_now()

                last_scan_duration = round(
                    time.time() - started,
                    3,
                )

                print(
                    "[Scheduler] scan complete "
                    f"duration={last_scan_duration}s "
                    f"status={result['status']}"
                )

            except Exception as e:

                last_scan_error = str(e)

                print(
                    "[Scheduler] scan error:",
                    e,
                )

            finally:

                last_scan_completed = utc_now()

                last_scan_duration = round(
                    time.time() - started,
                    3,
                )

                scan_lock.release()

        else:

            print(
                "[Scheduler] scan skipped "
                "because another scan is running"
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
        target=scheduler_loop,
        daemon=True,
        name="crypto-alert-scheduler",
    )

    thread.start()
