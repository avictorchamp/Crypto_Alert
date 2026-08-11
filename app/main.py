from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.crypto.price import get_market
from app.crypto.analyzer import analyze
from app.telegram.bot import send_message

from app.crypto.binance_account import get_portfolio
from app.crypto.binance_position import get_positions

from app.crypto.portfolio_monitor import (
    run_portfolio_monitor,
)

import threading
import time
from datetime import datetime, timezone


# =========================================================
# CRYPTO ALERT
# Version 3.4.1
#
# SYSTEM
#
# 1. WATCHLIST
#    - Always scans for opportunities
#    - Works even when portfolio is empty
#
# 2. PORTFOLIO MONITOR
#    - Monitors assets actually held
#    - Uses portfolio_monitor.py
#    - Binance TH READ ONLY
#
# 3. TELEGRAM
#    - Sends important alerts
#    - Cooldown protection
#
# 4. SCHEDULER
#    - Automatic scan every 5 minutes
#
# NO AUTOMATIC TRADING
# =========================================================


VERSION = "3.4.1"

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
# FORMAT NUMBER
# =========================================================

def fmt(
    value,
    digits=4,
):

    number = to_float(
        value
    )

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

        send_message(
            message
        )

        return {
            "status":
                "success",

            "test":
                True,

            "version":
                VERSION,

            "telegram":
                True,

            "message":
                "Test alert sent",
        }

    except Exception as e:

        return JSONResponse(
            status_code=500,

            content={
                "status":
                    "error",

                "test":
                    True,

                "version":
                    VERSION,

                "telegram":
                    False,

                "message":
                    str(e),
            },
        )


# =========================================================
# MARKET REGIME
# =========================================================

def get_market_regime(
    result,
):

    ema20 = to_float(
        result.get(
            "ema20"
        )
    )

    ema50 = to_float(
        result.get(
            "ema50"
        )
    )

    if (
        ema20 is None
        or ema50 is None
    ):

        return {
            "status":
                "UNKNOWN",

            "score":
                0,

            "reason":
                "EMA data unavailable",
        }

    if ema50 == 0:

        return {
            "status":
                "UNKNOWN",

            "score":
                0,

            "reason":
                "Invalid EMA50",
        }

    difference = (
        (
            ema20
            - ema50
        )
        / abs(ema50)
    ) * 100

    if abs(
        difference
    ) < 0.05:

        return {
            "status":
                "NEUTRAL",

            "score":
                50,

            "reason":
                "EMA20 and EMA50 are close",
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
            "status":
                "BULLISH",

            "score":
                score,

            "reason":
                "EMA20 above EMA50",
        }

    return {
        "status":
            "BEARISH",

        "score":
            score,

        "reason":
            "EMA20 below EMA50",
    }


# =========================================================
# WATCHLIST TRADE STATUS
# =========================================================

def get_trade_status(
    result,
):

    price = to_float(
        result.get(
            "price"
        )
    )

    entry = result.get(
        "entry",
        {},
    ) or {}

    entry_low = to_float(
        entry.get(
            "low"
        )
    )

    entry_high = to_float(
        entry.get(
            "high"
        )
    )

    quality = to_float(
        result.get(
            "quality_score"
        )
    )

    rsi = to_float(
        result.get(
            "rsi"
        )
    )

    risk_reward = to_float(
        result.get(
            "risk_reward"
        )
    )

    signal = result.get(
        "signal",
        "WAIT",
    )

    # -----------------------------------------------------
    # QUALITY
    # -----------------------------------------------------

    if (
        quality is not None
        and quality < MIN_QUALITY
    ):

        return {
            "status":
                "LOW_QUALITY",

            "action":
                "AVOID",

            "reason":
                "Quality below minimum",
        }

    # -----------------------------------------------------
    # RSI
    # -----------------------------------------------------

    if rsi is not None:

        if (
            signal in BUY_SIGNALS
            and rsi >= 75
        ):

            return {
                "status":
                    "RSI_OVERBOUGHT",

                "action":
                    "WAIT",

                "reason":
                    "RSI too high for BUY",
            }

        if (
            signal in SELL_SIGNALS
            and rsi <= 25
        ):

            return {
                "status":
                    "RSI_OVERSOLD",

                "action":
                    "WAIT",

                "reason":
                    "RSI too low for SELL",
            }

    # -----------------------------------------------------
    # RISK / REWARD
    # -----------------------------------------------------

    if (
        risk_reward is not None
        and risk_reward < MIN_RISK_REWARD
    ):

        return {
            "status":
                "LOW_RISK_REWARD",

            "action":
                "AVOID",

            "reason":
                "Risk/reward below minimum",
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
                "status":
                    "BELOW_ENTRY",

                "action":
                    "WAIT_FOR_ENTRY",

                "reason":
                    "Price below entry zone",
            }

        if price > entry_high:

            return {
                "status":
                    "ABOVE_ENTRY",

                "action":
                    "WAIT_FOR_ENTRY",

                "reason":
                    "Price above entry zone",
            }

        return {
            "status":
                "IN_ENTRY",

            "action":
                "READY",

            "reason":
                "Price inside entry zone",
        }

    return {
        "status":
            "WAIT",

        "action":
            "WAIT",

        "reason":
            "No actionable signal",
    }


# =========================================================
# WATCHLIST ALERT DECISION
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
        result.get(
            "quality_score"
        )
    )

    risk_reward = to_float(
        result.get(
            "risk_reward"
        )
    )

    # -----------------------------------------------------
    # SIGNAL
    # -----------------------------------------------------

    if signal not in (
        BUY_SIGNALS
        | SELL_SIGNALS
    ):

        return {
            "allowed":
                False,

            "reason":
                "Signal not alertable",
        }

    # -----------------------------------------------------
    # QUALITY
    # -----------------------------------------------------

    if quality is None:

        return {
            "allowed":
                False,

            "reason":
                "Quality unavailable",
        }

    if quality < MIN_QUALITY:

        return {
            "allowed":
                False,

            "reason":
                "Quality below threshold",
        }

    # -----------------------------------------------------
    # RISK / REWARD
    # -----------------------------------------------------

    if risk_reward is None:

        return {
            "allowed":
                False,

            "reason":
                "Risk/reward unavailable",
        }

    if risk_reward < MIN_RISK_REWARD:

        return {
            "allowed":
                False,

            "reason":
                "Risk/reward below threshold",
        }

    # -----------------------------------------------------
    # MARKET REGIME
    # -----------------------------------------------------

    if signal in BUY_SIGNALS:

        if regime["status"] != "BULLISH":

            return {
                "allowed":
                    False,

                "reason":
                    "BUY blocked by market regime",
            }

    if signal in SELL_SIGNALS:

        if regime["status"] != "BEARISH":

            return {
                "allowed":
                    False,

                "reason":
                    "SELL blocked by market regime",
            }

    # -----------------------------------------------------
    # ENTRY
    # -----------------------------------------------------

    if trade["status"] != "IN_ENTRY":

        return {
            "allowed":
                False,

            "reason":
                "Price not inside entry zone",
        }

    return {
        "allowed":
            True,

        "reason":
            "All conditions passed",
    }


# =========================================================
# SEND WATCHLIST ALERT
# =========================================================

def send_watchlist_alert(
    coin,
    result,
    regime,
    trade,
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
{risk_reward}

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
    result,
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
        trade,
    )

    if not decision["allowed"]:

        return {
            "sent":
                False,

            "reason":
                decision["reason"],

            "market_regime":
                regime["status"],

            "trade_status":
                trade["status"],

            "trade_action":
                trade["action"],
        }

    signal = result.get(
        "signal"
    )

    now = time.time()

    with state_lock:

        previous_signal = (
            last_signal.get(
                coin
            )
        )

        previous_time = (
            last_alert_time.get(
                coin,
                0
            )
        )

    if previous_signal == signal:

        elapsed = (
            now
            - previous_time
        )

        if elapsed < ALERT_COOLDOWN:

            return {
                "sent":
                    False,

                "reason":
                    "Duplicate signal cooldown",

                "cooldown_remaining":
                    round(
                        ALERT_COOLDOWN
                        - elapsed,
                        1,
                    ),

                "market_regime":
                    regime["status"],

                "trade_status":
                    trade["status"],

                "trade_action":
                    trade["action"],
            }

    try:

        send_watchlist_alert(
            coin,
            result,
            regime,
            trade,
        )

    except Exception as e:

        return {
            "sent":
                False,

            "reason":
                f"Telegram error: {e}",

            "market_regime":
                regime["status"],

            "trade_status":
                trade["status"],

            "trade_action":
                trade["action"],
        }

    with state_lock:

        last_signal[
            coin
        ] = signal

        last_alert_time[
            coin
        ] = now

    return {
        "sent":
            True,

        "reason":
            "New signal",

        "market_regime":
            regime["status"],

        "trade_status":
            trade["status"],

        "trade_action":
            trade["action"],
    }


# =========================================================
# WATCHLIST SCAN
# =========================================================

def run_watchlist_scan():

    results = []

    alerts_sent = []

    market = get_market()

    # -----------------------------------------------------
    # Normalize market response
    # -----------------------------------------------------

    if isinstance(
        market,
        dict,
    ):

        items = []

        for coin, data in market.items():

            if isinstance(
                data,
                dict,
            ):

                item = dict(
                    data
                )

                item.setdefault(
                    "coin",
                    coin,
                )

                items.append(
                    item
                )

    elif isinstance(
        market,
        list,
    ):

        items = market

    else:

        raise RuntimeError(
            "Unsupported get_market() response"
        )

    # -----------------------------------------------------
    # Analyze each coin
    # -----------------------------------------------------

    for item in items:

        coin = item.get(
            "coin"
        )

        if not coin:

            continue

        coin = str(
            coin
        ).upper()

        try:

            try:

                result = analyze(
                    item
                )

            except TypeError:

                result = analyze(
                    coin,
                    item
                )

        except Exception as e:

            results.append(
                {
                    "coin":
                        coin,

                    "status":
                        "ERROR",

                    "error":
                        str(e),
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
            coin,
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
        ] = trade[
            "status"
        ]

        result[
            "trade_action"
        ] = trade[
            "action"
        ]

        alert = process_watchlist_alert(
            coin,
            result,
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

            alerts_sent.append(
                coin
            )

    return {
        "status":
            "success",

        "count":
            len(results),

        "alerts_sent":
            alerts_sent,

        "data":
            results,
    }


# =========================================================
# BUILD MARKET DATA FOR PORTFOLIO MONITOR
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
                ""
            )
        ).upper()

        if not coin:

            continue

        market_data[
            coin
        ] = item

    return market_data


# =========================================================
# PORTFOLIO MONITOR
#
# IMPORTANT
#
# Uses portfolio_monitor.py v3.4.0
#
# run_portfolio_monitor(
#     portfolio_response,
#     market_data,
#     rules
# )
#
# =========================================================

def run_portfolio_scan(
    watchlist_data,
):

    # -----------------------------------------------------
    # Get current positions
    # -----------------------------------------------------

    positions_response = get_positions()

    if not isinstance(
        positions_response,
        dict,
    ):

        positions_response = {
            "status":
                "success",

            "positions":
                [],
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
    # Market data
    # -----------------------------------------------------

    market_data = build_market_data(
        watchlist_data
    )

    # -----------------------------------------------------
    # Portfolio response expected
    # by portfolio_monitor.py
    # -----------------------------------------------------

    portfolio_response = {
        "status":
            "success",

        "account_type":
            "READ_ONLY",

        "positions":
            positions,
    }

    # -----------------------------------------------------
    # Run real portfolio monitor
    # -----------------------------------------------------

    monitored = run_portfolio_monitor(
        portfolio_response=portfolio_response,

        market_data=market_data,

        rules={
            "minimum_quality":
                MIN_QUALITY,

            "minimum_risk_reward":
                MIN_RISK_REWARD,
        },
    )

    # -----------------------------------------------------
    # Return
    # -----------------------------------------------------

    return {
        "status":
            "success",

        "account_type":
            "READ_ONLY",

        "position_count":
            monitored.get(
                "position_count",
                len(positions),
            ),

        "high_priority_count":
            monitored.get(
                "high_priority_count",
                0,
            ),

        "positions":
            monitored.get(
                "positions",
                [],
            ),

        "high_priority":
            monitored.get(
                "high_priority",
                [],
            ),

        "alerts":
            monitored.get(
                "alerts",
                [],
            ),

        "read_only":
            True,
    }


# =========================================================
# FULL SCAN
#
# WATCHLIST ALWAYS RUNS
# PORTFOLIO ALWAYS RUNS
#
# Portfolio empty != Watchlist stopped
# =========================================================

def run_full_scan():

    global last_watchlist_result

    global last_portfolio_result

    errors = []

    # =====================================================
    # WATCHLIST
    # =====================================================

    try:

        watchlist = run_watchlist_scan()

    except Exception as e:

        errors.append(
            {
                "module":
                    "watchlist",

                "error":
                    str(e),
            }
        )

        watchlist = {
            "status":
                "error",

            "count":
                0,

            "alerts_sent":
                [],

            "data":
                [],

            "error":
                str(e),
        }

    watchlist_data = watchlist.get(
        "data",
        []
    )

    last_watchlist_result = (
        watchlist_data
    )

    # =====================================================
    # PORTFOLIO
    #
    # Runs even if portfolio is empty.
    # =====================================================

    try:

        portfolio = run_portfolio_scan(
            watchlist_data
        )

    except Exception as e:

        errors.append(
            {
                "module":
                    "portfolio",

                "error":
                    str(e),
            }
        )

        portfolio = {
            "status":
                "error",

            "account_type":
                "READ_ONLY",

            "position_count":
                0,

            "positions":
                [],

            "high_priority":
                [],

            "alerts":
                [],

            "error":
                str(e),
        }

    last_portfolio_result = (
        portfolio.get(
            "positions",
            []
        )
    )

    return {
        "status":
            (
                "success"
                if not errors
                else "partial_success"
            ),

        "watchlist":
            watchlist,

        "portfolio":
            portfolio,

        "errors":
            errors,
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
                "status":
                    "busy",

                "version":
                    VERSION,

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
            time.time()
            - started,
            3,
        )

        return {
            "status":
                result[
                    "status"
                ],

            "version":
                VERSION,

            "watchlist":
                result[
                    "watchlist"
                ],

            "portfolio":
                result[
                    "portfolio"
                ],

            "errors":
                result[
                    "errors"
                ],
        }

    except Exception as e:

        last_scan_error = str(e)

        return JSONResponse(
            status_code=500,

            content={
                "status":
                    "error",

                "version":
                    VERSION,

                "message":
                    str(e),
            },
        )

    finally:

        last_scan_completed = utc_now()

        last_scan_duration = round(
            time.time()
            - started,
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
            "status":
                "success",

            "version":
                VERSION,

            "source":
                "Binance TH",

            "account_mode":
                "READ_ONLY",

            "portfolio":
                result,
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
                    str(e),
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
            "status":
                "success",

            "version":
                VERSION,

            "source":
                "Binance TH",

            "account_mode":
                "READ_ONLY",

            "positions":
                result,
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
                    str(e),
            },
        )


# =========================================================
# PORTFOLIO MONITOR
#
# Manual test endpoint
# =========================================================

@app.get("/portfolio-monitor")
def portfolio_monitor():

    try:

        # Run watchlist first so that
        # portfolio monitor receives
        # current market data.

        watchlist = run_watchlist_scan()

        portfolio = run_portfolio_scan(
            watchlist.get(
                "data",
                []
            )
        )

        return {
            "status":
                "success",

            "version":
                VERSION,

            "source":
                "Binance TH",

            "account_mode":
                "READ_ONLY",

            "portfolio_monitor":
                portfolio,
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

                "stage":
                    "portfolio_monitor",

                "message":
                    str(e),
            },
        )


# =========================================================
# STATUS
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
            last_scan_error,
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
                SCAN_INTERVAL,
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

            "portfolio_monitor":
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

        # -------------------------------------------------
        # Prevent overlapping scans
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
                    time.time()
                    - started,
                    3,
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
                    e,
                )

            finally:

                last_scan_completed = utc_now()

                last_scan_duration = round(
                    time.time()
                    - started,
                    3,
                )

                scan_lock.release()

        else:

            print(
                "[Scheduler] scan skipped "
                "because another scan is running"
            )

        # -------------------------------------------------
        # 5 minutes
        # -------------------------------------------------

        time.sleep(
            SCAN_INTERVAL
        )


# =========================================================
# START SCHEDULER
# =========================================================

@app.on_event(
    "startup"
)
def startup_event():

    thread = threading.Thread(
        target=scheduler_loop,

        daemon=True,

        name=
            "crypto-alert-scheduler",
    )

    thread.start()
