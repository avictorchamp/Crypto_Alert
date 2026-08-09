from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.crypto.price import get_market
from app.crypto.analyzer import analyze
from app.telegram.bot import send_message
from app.crypto.binance_account import get_portfolio
from app.crypto.binance_position import get_positions

import threading
import time
from datetime import datetime, timezone


# =========================================================
# CRYPTO ALERT V3.3.0
#
# TWO PARALLEL SYSTEMS
#
# 1. WATCHLIST
#    - Always scans for new opportunities
#    - Works even when portfolio is empty
#
# 2. PORTFOLIO MONITOR
#    - Always monitors coins actually held
#    - Uses Binance TH READ-ONLY data
#
# No automatic trading.
# =========================================================


VERSION = "3.3.0"

SCAN_INTERVAL = 300
ALERT_COOLDOWN = 1800

MIN_QUALITY = 70
MIN_RISK_REWARD = 1.0


BUY_SIGNALS = {
    "BUY SETUP",
    "STRONG BUY"
}

SELL_SIGNALS = {
    "SELL WATCH",
    "STRONG SELL"
}


# =========================================================
# FASTAPI
# =========================================================

app = FastAPI(
    title="Crypto Alert",
    version=VERSION
)


# =========================================================
# GLOBAL STATE
# =========================================================

last_signal = {}
last_alert_time = {}

last_position_action = {}
last_position_alert_time = {}

scheduler_started_at = None

last_scan_started = None
last_scan_completed = None
last_scan_duration = None
last_scan_error = None

last_watchlist_result = []
last_portfolio_result = []

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
# PORTFOLIO MONITOR
# =========================================================

from app.crypto.portfolio_monitor import (
    run_portfolio_monitor,
)


@app.get("/portfolio-monitor")
def portfolio_monitor():

    try:

        # ---------------------------------------------
        # Get current Binance TH portfolio
        # ---------------------------------------------

        portfolio = get_portfolio()

        if portfolio.get(
            "status"
        ) != "success":

            return {
                "status": "error",
                "version": VERSION,
                "stage": "portfolio",
                "portfolio": portfolio
            }

        # ---------------------------------------------
        # Build market data
        # ---------------------------------------------

        market_data = {}

        scan_result = scan()

        if (
            scan_result
            and scan_result.get(
                "status"
            ) == "success"
        ):

            for item in scan_result.get(
                "data",
                []
            ):

                coin = str(
                    item.get(
                        "coin",
                        ""
                    )
                ).upper()

                if coin:

                    market_data[
                        coin
                    ] = item

        # ---------------------------------------------
        # Monitor positions
        # ---------------------------------------------

        result = run_portfolio_monitor(
            portfolio_response=portfolio,
            market_data=market_data
        )

        return {
            "status":
                "success",

            "version":
                VERSION,

            "portfolio":
                portfolio,

            "monitor":
                result
        }

    except Exception as e:

        return {
            "status":
                "error",

            "version":
                VERSION,

            "stage":
                "portfolio_monitor",

            "message":
                str(e)
        }

# =========================================================
# SAFE NUMBER
# =========================================================

def to_float(value, default=None):

    try:
        return float(value)

    except (
        TypeError,
        ValueError
    ):

        return default


# =========================================================
# FORMAT NUMBER
# =========================================================

def fmt(value, digits=4):

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

    ema20 = to_float(
        result.get("ema20")
    )

    ema50 = to_float(
        result.get("ema50")
    )

    if ema20 is None or ema50 is None:

        return {
            "status": "UNKNOWN",
            "score": 0,
            "reason": "EMA data unavailable"
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

    strength = min(
        50,
        abs(difference) * 100
    )

    score = round(
        50 + strength
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
# WATCHLIST TRADE STATUS
# =========================================================

def get_trade_status(result):

    signal = result.get(
        "signal",
        "WAIT"
    )

    price = to_float(
        result.get("price")
    )

    entry = result.get(
        "entry",
        {}
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

    # -----------------------------------------------------
    # QUALITY
    # -----------------------------------------------------

    if quality is not None:

        if quality < MIN_QUALITY:

            return {
                "status": "LOW_QUALITY",
                "action": "AVOID",
                "reason": "Quality below minimum"
            }

    # -----------------------------------------------------
    # RSI
    # -----------------------------------------------------

    if rsi is not None:

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

    # -----------------------------------------------------
    # RISK / REWARD
    # -----------------------------------------------------

    if risk_reward is not None:

        if risk_reward < MIN_RISK_REWARD:

            return {
                "status": "LOW_RISK_REWARD",
                "action": "AVOID",
                "reason": "Risk/reward below minimum"
            }

    # -----------------------------------------------------
    # ENTRY
    # -----------------------------------------------------

    if (
        price is not None
        and entry_low is not None
        and entry_high is not None
    ):

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

    return {
        "status": "WAIT",
        "action": "WAIT",
        "reason": "No actionable signal"
    }


# =========================================================
# WATCHLIST ALERT DECISION
# =========================================================

def evaluate_watchlist_alert(
    result,
    regime,
    trade
):

    signal = result.get(
        "signal",
        "WAIT"
    )

    quality = to_float(
        result.get("quality_score")
    )

    rr = to_float(
        result.get("risk_reward")
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
            "reason": "Quality unavailable"
        }

    if quality < MIN_QUALITY:

        return {
            "allowed": False,
            "reason": "Quality below threshold"
        }

    # -----------------------------------------------------
    # RR
    # -----------------------------------------------------

    if rr is None:

        return {
            "allowed": False,
            "reason": "Risk/reward unavailable"
        }

    if rr < MIN_RISK_REWARD:

        return {
            "allowed": False,
            "reason": "Risk/reward below threshold"
        }

    # -----------------------------------------------------
    # MARKET REGIME
    # -----------------------------------------------------

    if signal in BUY_SIGNALS:

        if regime["status"] != "BULLISH":

            return {
                "allowed": False,
                "reason": "BUY blocked by market regime"
            }

    if signal in SELL_SIGNALS:

        if regime["status"] != "BEARISH":

            return {
                "allowed": False,
                "reason": "SELL blocked by market regime"
            }

    # -----------------------------------------------------
    # ENTRY
    # -----------------------------------------------------

    if trade["status"] != "IN_ENTRY":

        return {
            "allowed": False,
            "reason": "Price not inside entry zone"
        }

    return {
        "allowed": True,
        "reason": "All conditions passed"
    }


# =========================================================
# WATCHLIST TELEGRAM
# =========================================================

def send_watchlist_alert(
    coin,
    result,
    regime,
    trade
):

    signal = result.get(
        "signal"
    )

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

    price = result.get(
        "price"
    )

    entry = result.get(
        "entry",
        {}
    ) or {}

    stop_loss = result.get(
        "stop_loss"
    )

    take_profit = result.get(
        "take_profit",
        {}
    ) or {}

    rr = result.get(
        "risk_reward"
    )

    reasons = result.get(
        "reason",
        []
    )

    reason_text = "\n".join(
        f"• {x}"
        for x in reasons
    ) or "• N/A"

    message = f"""
🟢 BUY OPPORTUNITY

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
{fmt(entry.get("low"))}
-
{fmt(entry.get("high"))}

🛑 STOP LOSS
{fmt(stop_loss)}

🎯 TP1
{fmt(take_profit.get("tp1"))}

🎯 TP2
{fmt(take_profit.get("tp2"))}

⚖️ RISK / REWARD
{rr}

🧠 REASON
{reason_text}

━━━━━━━━━━━━━━━━━━

⚠️ MANUAL EXECUTION ONLY
No automatic trading.
"""

    send_message(
        message
    )


# =========================================================
# PROCESS WATCHLIST ALERT
# =========================================================

def process_watchlist_alert(
    coin,
    result
):

    regime = get_market_regime(
        result
    )

    trade = get_trade_status(
        result
    )

    decision = evaluate_watchlist_alert(
        result,
        regime,
        trade
    )

    if not decision["allowed"]:

        return {
            "sent": False,
            "reason": decision["reason"],
            "market_regime":
                regime["status"],
            "trade_status":
                trade["status"],
            "trade_action":
                trade["action"]
        }

    signal = result.get(
        "signal"
    )

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

        elapsed = (
            now - previous_time
        )

        if elapsed < ALERT_COOLDOWN:

            return {
                "sent": False,
                "reason":
                    "Duplicate signal cooldown",
                "cooldown_remaining":
                    round(
                        ALERT_COOLDOWN
                        - elapsed,
                        1
                    ),
                "market_regime":
                    regime["status"],
                "trade_status":
                    trade["status"],
                "trade_action":
                    trade["action"]
            }

    try:

        send_watchlist_alert(
            coin,
            result,
            regime,
            trade
        )

    except Exception as e:

        return {
            "sent": False,
            "reason":
                f"Telegram error: {e}",
            "market_regime":
                regime["status"],
            "trade_status":
                trade["status"],
            "trade_action":
                trade["action"]
        }

    with state_lock:

        last_signal[coin] = signal

        last_alert_time[coin] = now

    return {
        "sent": True,
        "reason": "New signal",
        "market_regime":
            regime["status"],
        "trade_status":
            trade["status"],
        "trade_action":
            trade["action"]
    }


# =========================================================
# POSITION ACTION ENGINE
#
# This is NOT a trading engine.
# It only tells the user what action to review.
# =========================================================

def evaluate_position(
    position
):

    asset = position.get(
        "asset"
    )

    quantity = to_float(
        position.get("quantity"),
        0
    )

    entry = to_float(
        position.get("average_entry")
    )

    current = to_float(
        position.get("current_price")
    )

    pnl = to_float(
        position.get(
            "unrealized_pnl_percent"
        )
    )

    status = position.get(
        "cost_basis_status"
    )

    # -----------------------------------------------------
    # No cost basis
    # -----------------------------------------------------

    if entry is None:

        return {
            "action": "MONITOR",
            "status": "COST_BASIS_UNKNOWN",
            "reason":
                "Cannot determine reliable entry price"
        }

    # -----------------------------------------------------
    # No current price
    # -----------------------------------------------------

    if current is None:

        return {
            "action": "MONITOR",
            "status": "PRICE_UNAVAILABLE",
            "reason":
                "Current market price unavailable"
        }

    # -----------------------------------------------------
    # P/L
    # -----------------------------------------------------

    if pnl is None:

        pnl = (
            (
                current - entry
            )
            / entry
        ) * 100

    # -----------------------------------------------------
    # Emergency loss
    # -----------------------------------------------------

    if pnl <= -5:

        return {
            "action": "REVIEW_EXIT",
            "status": "STOP_RISK",
            "reason":
                "Position is down 5% or more",
            "pnl_percent":
                round(pnl, 4)
        }

    # -----------------------------------------------------
    # Strong profit
    # -----------------------------------------------------

    if pnl >= 10:

        return {
            "action": "REVIEW_TAKE_PROFIT",
            "status": "PROFIT_10_PLUS",
            "reason":
                "Position profit is 10% or more",
            "pnl_percent":
                round(pnl, 4)
        }

    # -----------------------------------------------------
    # Moderate profit
    # -----------------------------------------------------

    if pnl >= 5:

        return {
            "action": "REVIEW_TAKE_PROFIT",
            "status": "PROFIT_5_PLUS",
            "reason":
                "Position profit is 5% or more",
            "pnl_percent":
                round(pnl, 4)
        }

    # -----------------------------------------------------
    # Small profit
    # -----------------------------------------------------

    if pnl > 0:

        return {
            "action": "HOLD",
            "status": "PROFIT",
            "reason":
                "Position remains profitable",
            "pnl_percent":
                round(pnl, 4)
        }

    # -----------------------------------------------------
    # Small loss
    # -----------------------------------------------------

    return {
        "action": "HOLD",
        "status": "LOSS",
        "reason":
            "Position remains within monitoring range",
        "pnl_percent":
            round(pnl, 4)
    }


# =========================================================
# POSITION TELEGRAM
# =========================================================

def send_position_alert(
    position,
    action
):

    asset = position.get(
        "asset"
    )

    quantity = position.get(
        "quantity"
    )

    entry = position.get(
        "average_entry"
    )

    current = position.get(
        "current_price"
    )

    pnl = action.get(
        "pnl_percent"
    )

    status = action.get(
        "status"
    )

    reason = action.get(
        "reason"
    )

    if action["action"] == "REVIEW_EXIT":

        title = "🔴 POSITION EXIT REVIEW"

    elif action["action"] == "REVIEW_TAKE_PROFIT":

        title = "🟡 TAKE PROFIT REVIEW"

    else:

        title = "📊 POSITION UPDATE"

    message = f"""
{title}

━━━━━━━━━━━━━━━━━━
{asset}
━━━━━━━━━━━━━━━━━━

📦 QUANTITY
{quantity}

💰 AVERAGE ENTRY
{fmt(entry)}

📈 CURRENT PRICE
{fmt(current)}

📊 P/L
{fmt(pnl, 2)}%

🎯 ACTION
{action["action"]}

📌 STATUS
{status}

🧠 REASON
{reason}

━━━━━━━━━━━━━━━━━━

⚠️ MANUAL EXECUTION ONLY
No automatic trading.
"""

    send_message(
        message
    )


# =========================================================
# PROCESS POSITION
# =========================================================

def process_position(
    position
):

    asset = position.get(
        "asset"
    )

    if not asset:

        return {
            "sent": False,
            "reason":
                "Missing asset"
        }

    action = evaluate_position(
        position
    )

    action_name = action[
        "action"
    ]

    # -----------------------------------------------------
    # HOLD is intentionally not sent every 5 minutes.
    # -----------------------------------------------------

    if action_name == "HOLD":

        return {
            **action,
            "sent": False,
            "reason":
                "Normal monitoring"
        }

    now = time.time()

    with state_lock:

        previous_action = (
            last_position_action.get(
                asset
            )
        )

        previous_time = (
            last_position_alert_time.get(
                asset,
                0
            )
        )

    # -----------------------------------------------------
    # Avoid repeated EXIT / TP alerts.
    # -----------------------------------------------------

    if previous_action == action_name:

        elapsed = (
            now - previous_time
        )

        if elapsed < ALERT_COOLDOWN:

            return {
                **action,
                "sent": False,
                "reason":
                    "Duplicate position alert cooldown",
                "cooldown_remaining":
                    round(
                        ALERT_COOLDOWN
                        - elapsed,
                        1
                    )
            }

    try:

        send_position_alert(
            position,
            action
        )

    except Exception as e:

        return {
            **action,
            "sent": False,
            "reason":
                f"Telegram error: {e}"
        }

    with state_lock:

        last_position_action[
            asset
        ] = action_name

        last_position_alert_time[
            asset
        ] = now

    return {
        **action,
        "sent": True,
        "reason":
            "Position action alert sent"
    }


# =========================================================
# WATCHLIST SCAN
# =========================================================

def run_watchlist_scan():

    results = []

    alerts = []

    market = get_market()

    # -----------------------------------------------------
    # get_market() may return:
    #
    # {
    #   "BTC": {...},
    #   "ETH": {...}
    # }
    #
    # or:
    #
    # [
    #   {...},
    #   {...}
    # ]
    # -----------------------------------------------------

    if isinstance(
        market,
        dict
    ):

        items = []

        for coin, data in market.items():

            if isinstance(
                data,
                dict
            ):

                item = dict(
                    data
                )

                item.setdefault(
                    "coin",
                    coin
                )

                items.append(
                    item
                )

    elif isinstance(
        market,
        list
    ):

        items = market

    else:

        raise RuntimeError(
            "Unsupported get_market() response"
        )

    for item in items:

        coin = item.get(
            "coin"
        )

        if not coin:
            continue

        try:

            result = analyze(
                item
            )

        except TypeError:

            # Compatibility for analyzers
            # that expect coin/data separately.
            try:

                result = analyze(
                    coin,
                    item
                )

            except Exception as e:

                results.append(
                    {
                        "coin": coin,
                        "status": "ERROR",
                        "error": str(e)
                    }
                )

                continue

        except Exception as e:

            results.append(
                {
                    "coin": coin,
                    "status": "ERROR",
                    "error": str(e)
                }
            )

            continue

        if result is None:

            continue

        result = dict(
            result
        )

        result.setdefault(
            "coin",
            coin
        )

        regime = get_market_regime(
            result
        )

        trade = get_trade_status(
            result
        )

        result[
            "market_regime"
        ] = regime

        result[
            "trade_status"
        ] = trade["status"]

        result[
            "trade_action"
        ] = trade["action"]

        alert = process_watchlist_alert(
            coin,
            result
        )

        result[
            "alert_status"
        ] = alert

        results.append(
            result
        )

        if alert.get(
            "sent"
        ):

            alerts.append(
                coin
            )

    return {
        "status": "success",
        "count": len(results),
        "alerts_sent": alerts,
        "data": results
    }


# =========================================================
# PORTFOLIO MONITOR
# =========================================================

def run_portfolio_monitor():

    result = get_positions()

    positions = result.get(
        "positions",
        []
    )

    monitored = []

    alerts = []

    for position in positions:

        if not isinstance(
            position,
            dict
        ):

            continue

        action = process_position(
            position
        )

        record = dict(
            position
        )

        record[
            "monitor"
        ] = action

        monitored.append(
            record
        )

        if action.get(
            "sent"
        ):

            alerts.append(
                position.get(
                    "asset"
                )
            )

    return {
        "status": "success",
        "position_count":
            len(monitored),
        "alerts_sent":
            alerts,
        "positions":
            monitored
    }


# =========================================================
# COMPLETE SCAN
#
# WATCHLIST and PORTFOLIO ALWAYS RUN INDEPENDENTLY.
# =========================================================

def run_full_scan():

    global last_watchlist_result
    global last_portfolio_result

    watchlist = None
    portfolio = None

    errors = []

    # -----------------------------------------------------
    # WATCHLIST
    # -----------------------------------------------------

    try:

        watchlist = run_watchlist_scan()

    except Exception as e:

        errors.append(
            {
                "module": "watchlist",
                "error": str(e)
            }
        )

        watchlist = {
            "status": "error",
            "error": str(e),
            "data": []
        }

    # -----------------------------------------------------
    # PORTFOLIO
    #
    # IMPORTANT:
    # This runs even if Watchlist failed.
    # -----------------------------------------------------

    try:

        portfolio = run_portfolio_monitor()

    except Exception as e:

        errors.append(
            {
                "module": "portfolio",
                "error": str(e)
            }
        )

        portfolio = {
            "status": "error",
            "error": str(e),
            "positions": []
        }

    last_watchlist_result = (
        watchlist.get(
            "data",
            []
        )
    )

    last_portfolio_result = (
        portfolio.get(
            "positions",
            []
        )
    )

    return {
        "status":
            "success"
            if not errors
            else "partial_success",

        "watchlist":
            watchlist,

        "portfolio":
            portfolio,

        "errors":
            errors
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

    # -----------------------------------------------------
    # Prevent concurrent scans.
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

    started = time.time()

    last_scan_started = utc_now()
    last_scan_error = None

    try:

        result = run_full_scan()

        last_scan_completed = utc_now()

        last_scan_duration = round(
            time.time() - started,
            3
        )

        return {
            "status":
                result["status"],

            "version":
                VERSION,

            "scan_interval_seconds":
                SCAN_INTERVAL,

            "watchlist":
                result["watchlist"],

            "portfolio":
                result["portfolio"],

            "errors":
                result["errors"]
        }

    except Exception as e:

        last_scan_error = str(e)

        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "version": VERSION,
                "message": str(e)
            }
        )

    finally:

        last_scan_completed = utc_now()

        last_scan_duration = round(
            time.time() - started,
            3
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
            "status":
                "success",

            "version":
                VERSION,

            "source":
                "Binance TH",

            "account_mode":
                "READ_ONLY",

            "portfolio":
                result
        }

    except Exception as e:

        return JSONResponse(
            status_code=500,
            content={
                "status":
                    "error",

                "version":
                    VERSION,

                "source":
                    "Binance TH",

                "account_mode":
                    "READ_ONLY",

                "message":
                    str(e)
            }
        )


# =========================================================
# POSITIONS
# =========================================================

@app.get("/positions")
def positions():

    try:

        result = get_positions()

        return {
            "status":
                "success",

            "version":
                VERSION,

            "source":
                "Binance TH",

            "account_mode":
                "READ_ONLY",

            "positions":
                result
        }

    except Exception as e:

        return JSONResponse(
            status_code=500,
            content={
                "status":
                    "error",

                "version":
                    VERSION,

                "source":
                    "Binance TH",

                "account_mode":
                    "READ_ONLY",

                "message":
                    str(e)
            }
        )


# =========================================================
# LAST RESULTS
# =========================================================

@app.get("/status")
def status():

    return {
        "status":
            "success",

        "version":
            VERSION,

        "watchlist_count":
            len(
                last_watchlist_result
            ),

        "portfolio_position_count":
            len(
                last_portfolio_result
            ),

        "last_scan_started":
            last_scan_started,

        "last_scan_completed":
            last_scan_completed,

        "last_scan_duration_seconds":
            last_scan_duration,

        "last_scan_error":
            last_scan_error
    }


# =========================================================
# HEALTH
# =========================================================

@app.get("/health")
def health():

    return {
        "status":
            "healthy",

        "service":
            "Crypto Alert",

        "version":
            VERSION,

        "rules": {
            "minimum_quality":
                MIN_QUALITY,

            "minimum_risk_reward":
                MIN_RISK_REWARD,

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
        },

        "modules": {
            "watchlist":
                "ACTIVE",

            "portfolio_monitor":
                "ACTIVE",

            "binance":
                "READ_ONLY",

            "telegram":
                "ACTIVE",

            "automatic_trading":
                "DISABLED"
        }
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

    # -----------------------------------------------------
    # Run immediately after startup.
    # -----------------------------------------------------

    while True:

        started = time.time()

        # -------------------------------------------------
        # Don't run if another scan is active.
        # -------------------------------------------------

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
                    3
                )

                print(
                    "[Scheduler] scan complete "
                    f"duration="
                    f"{last_scan_duration}s "
                    f"status="
                    f"{result['status']}"
                )

            except Exception as e:

                last_scan_error = str(e)

                print(
                    "[Scheduler] scan error:",
                    e
                )

            finally:

                last_scan_completed = utc_now()

                last_scan_duration = round(
                    time.time() - started,
                    3
                )

                scan_lock.release()

        else:

            print(
                "[Scheduler] scan skipped "
                "because another scan is running"
            )

        # -------------------------------------------------
        # Wait 5 minutes.
        # -------------------------------------------------

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
        name="crypto-alert-scheduler"
    )

    thread.start()

    print(
        f"Crypto Alert {VERSION} "
        "scheduler started"
    )


# =========================================================
# ROOT
# =========================================================

@app.get("/")
def root():

    return {
        "service":
            "Crypto Alert",

        "version":
            VERSION,

        "status":
            "running",

        "architecture": {
            "watchlist":
                "CONTINUOUS",

            "portfolio_monitor":
                "CONTINUOUS",

            "scheduler":
                "5_MINUTES",

            "binance":
                "READ_ONLY",

            "telegram":
                "ENABLED",

            "automatic_trading":
                "DISABLED"
        }
    }
