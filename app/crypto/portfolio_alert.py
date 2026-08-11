import time

from app.telegram.bot import send_message


# =========================================================
# PORTFOLIO ALERT
# VERSION 1.0.0
#
# Purpose:
#   Send Telegram alerts only when a held position
#   requires attention.
#
# READ ONLY
# NO BUY
# NO SELL
# NO ORDER
# =========================================================


VERSION = "1.0.0"

ALERT_COOLDOWN = 1800  # 30 minutes


# =========================================================
# STATE
# =========================================================

_last_alert = {}


# =========================================================
# HELPERS
# =========================================================

def safe_float(
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


def fmt(
    value,
    digits=6,
):

    number = safe_float(
        value
    )

    if number is None:
        return "N/A"

    return f"{number:,.{digits}f}"


# =========================================================
# COOLDOWN
# =========================================================

def check_cooldown(
    key,
):

    now = time.time()

    previous = _last_alert.get(
        key
    )

    if previous is None:
        return {
            "allowed": True,
            "remaining": 0,
        }

    elapsed = (
        now - previous
    )

    if elapsed >= ALERT_COOLDOWN:

        return {
            "allowed": True,
            "remaining": 0,
        }

    return {
        "allowed": False,
        "remaining": round(
            ALERT_COOLDOWN - elapsed,
            1,
        ),
    }


# =========================================================
# CLASSIFY POSITION ACTION
# =========================================================

def classify_position(
    position,
):

    pnl = safe_float(
        position.get(
            "unrealized_pnl_percent"
        )
    )

    state = position.get(
        "position_state"
    )

    market_regime = (
        position.get(
            "market_regime"
        )
        or {}
    )

    regime = market_regime.get(
        "status"
    )

    quality = safe_float(
        position.get(
            "quality_score"
        )
    )

    risk_reward = safe_float(
        position.get(
            "risk_reward"
        )
    )

    # =====================================================
    # COST BASIS UNKNOWN
    # =====================================================

    if pnl is None:

        return {
            "action":
                "MONITOR",

            "priority":
                "LOW",

            "reason":
                "Average entry price unavailable",
        }

    # =====================================================
    # STRONG PROFIT
    # =====================================================

    if pnl >= 15:

        return {
            "action":
                "TAKE_PROFIT_REVIEW",

            "priority":
                "HIGH",

            "reason":
                "Position profit is above 15%",
        }

    if pnl >= 10:

        return {
            "action":
                "TAKE_PROFIT_REVIEW",

            "priority":
                "HIGH",

            "reason":
                "Position profit is above 10%",
        }

    if pnl >= 5:

        return {
            "action":
                "TAKE_PROFIT_REVIEW",

            "priority":
                "MEDIUM",

            "reason":
                "Position profit is above 5%",
        }

    # =====================================================
    # LOSS
    # =====================================================

    if pnl <= -10:

        return {
            "action":
                "EXIT_REVIEW",

            "priority":
                "CRITICAL",

            "reason":
                "Position loss is below -10%",
        }

    if pnl <= -5:

        return {
            "action":
                "PROTECT",

            "priority":
                "HIGH",

            "reason":
                "Position loss reached -5%",
        }

    # =====================================================
    # BEARISH MARKET
    # =====================================================

    if regime == "BEARISH":

        return {
            "action":
                "EXIT_REVIEW",

            "priority":
                "HIGH",

            "reason":
                "Market regime is bearish",
        }

    # =====================================================
    # LOW QUALITY
    # =====================================================

    if (
        quality is not None
        and quality < 60
    ):

        return {
            "action":
                "REVIEW",

            "priority":
                "MEDIUM",

            "reason":
                "Current setup quality is low",
        }

    # =====================================================
    # LOW RISK / REWARD
    # =====================================================

    if (
        risk_reward is not None
        and risk_reward < 1.0
    ):

        return {
            "action":
                "REVIEW",

            "priority":
                "MEDIUM",

            "reason":
                "Current risk/reward is below 1.0",
        }

    # =====================================================
    # NORMAL
    # =====================================================

    return {
        "action":
            "HOLD",

        "priority":
            "LOW",

        "reason":
            "No immediate action required",
    }


# =========================================================
# BUILD TELEGRAM MESSAGE
# =========================================================

def build_message(
    position,
    decision,
):

    asset = position.get(
        "asset",
        "UNKNOWN",
    )

    symbol = position.get(
        "symbol",
        asset,
    )

    quantity = position.get(
        "quantity"
    )

    average_entry = position.get(
        "average_entry"
    )

    current_price = position.get(
        "current_price"
    )

    pnl_percent = position.get(
        "unrealized_pnl_percent"
    )

    pnl = position.get(
        "unrealized_pnl"
    )

    market_value = position.get(
        "market_value"
    )

    market_regime = (
        position.get(
            "market_regime"
        )
        or {}
    )

    regime = market_regime.get(
        "status",
        "UNKNOWN",
    )

    quality = position.get(
        "quality_score"
    )

    grade = position.get(
        "quality_grade"
    )

    action = decision.get(
        "action",
        "REVIEW",
    )

    priority = decision.get(
        "priority",
        "MEDIUM",
    )

    reason = decision.get(
        "reason",
        "",
    )

    if action == "TAKE_PROFIT_REVIEW":

        emoji = "🟢"

    elif action == "PROTECT":

        emoji = "🟠"

    elif action == "EXIT_REVIEW":

        emoji = "🔴"

    else:

        emoji = "🟡"

    pnl_text = (
        f"{fmt(pnl_percent, 2)}%"
        if pnl_percent is not None
        else "N/A"
    )

    message = f"""
{emoji} PORTFOLIO ALERT

━━━━━━━━━━━━━━━━━━
{asset}
{symbol}
━━━━━━━━━━━━━━━━━━

📌 ACTION
{action}

🚦 PRIORITY
{priority}

💰 CURRENT PRICE
{fmt(current_price)}

📦 QUANTITY
{fmt(quantity, 8)}

🎯 AVERAGE ENTRY
{fmt(average_entry)}

📊 UNREALIZED P/L
{pnl_text}

💵 P/L VALUE
{fmt(pnl)}

💼 MARKET VALUE
{fmt(market_value)}

📈 MARKET REGIME
{regime}

⭐ QUALITY
{quality if quality is not None else "N/A"}
{f"({grade})" if grade else ""}

🧠 REASON
{reason}

━━━━━━━━━━━━━━━━━━

⚠️ READ ONLY

No automatic BUY or SELL order
has been executed.

Review the position manually.
"""

    return message.strip()


# =========================================================
# SEND SINGLE POSITION ALERT
# =========================================================

def send_position_alert(
    position,
    force=False,
):

    asset = position.get(
        "asset",
        "UNKNOWN",
    )

    decision = classify_position(
        position
    )

    action = decision.get(
        "action"
    )

    priority = decision.get(
        "priority"
    )

    # -----------------------------------------------------
    # HOLD is intentionally silent
    # -----------------------------------------------------

    if action == "HOLD":

        return {
            "sent":
                False,

            "action":
                action,

            "reason":
                "No alert required",
        }

    # -----------------------------------------------------
    # Normal MONITOR is silent
    # -----------------------------------------------------

    if action == "MONITOR":

        return {
            "sent":
                False,

            "action":
                action,

            "reason":
                decision.get(
                    "reason"
                ),
        }

    # -----------------------------------------------------
    # Cooldown
    # -----------------------------------------------------

    cooldown_key = (
        f"{asset}:{action}"
    )

    if not force:

        cooldown = check_cooldown(
            cooldown_key
        )

        if not cooldown["allowed"]:

            return {
                "sent":
                    False,

                "action":
                    action,

                "reason":
                    "Duplicate alert cooldown",

                "cooldown_remaining":
                    cooldown["remaining"],
            }

    # -----------------------------------------------------
    # Telegram
    # -----------------------------------------------------

    message = build_message(
        position,
        decision,
    )

    try:

        send_message(
            message
        )

    except Exception as e:

        return {
            "sent":
                False,

            "action":
                action,

            "priority":
                priority,

            "reason":
                f"Telegram error: {e}",
        }

    _last_alert[
        cooldown_key
    ] = time.time()

    return {
        "sent":
            True,

        "action":
            action,

        "priority":
            priority,

        "reason":
            decision.get(
                "reason"
            ),
    }


# =========================================================
# MONITOR ALL POSITIONS
# =========================================================

def monitor_portfolio_alerts(
    positions,
    force=False,
):

    if not isinstance(
        positions,
        list,
    ):

        return {
            "status":
                "error",

            "version":
                VERSION,

            "message":
                "positions must be a list",
        }

    results = []

    alerts_sent = []

    high_priority = []

    for position in positions:

        if not isinstance(
            position,
            dict,
        ):

            continue

        decision = classify_position(
            position
        )

        if decision.get(
            "priority"
        ) in {
            "HIGH",
            "CRITICAL",
        }:

            high_priority.append(
                position.get(
                    "asset",
                    "UNKNOWN",
                )
            )

        result = send_position_alert(
            position,
            force=force,
        )

        asset = position.get(
            "asset",
            "UNKNOWN",
        )

        results.append(
            {
                "asset":
                    asset,

                "action":
                    result.get(
                        "action"
                    ),

                "priority":
                    result.get(
                        "priority",
                        decision.get(
                            "priority"
                        ),
                    ),

                "sent":
                    result.get(
                        "sent",
                        False,
                    ),

                "reason":
                    result.get(
                        "reason"
                    ),

                "cooldown_remaining":
                    result.get(
                        "cooldown_remaining"
                    ),
            }
        )

        if result.get(
            "sent"
        ):

            alerts_sent.append(
                asset
            )

    return {
        "status":
            "success",

        "version":
            VERSION,

        "position_count":
            len(positions),

        "high_priority":
            high_priority,

        "alerts_sent":
            alerts_sent,

        "results":
            results,
    }


# =========================================================
# TEST ALERT
# =========================================================

def test_portfolio_alert():

    position = {
        "asset":
            "BTC",

        "symbol":
            "BTC/THB",

        "quantity":
            0.01,

        "average_entry":
            2000000,

        "current_price":
            2250000,

        "unrealized_pnl_percent":
            12.5,

        "unrealized_pnl":
            2500,

        "market_value":
            22500,

        "market_regime": {
            "status":
                "BULLISH",
        },

        "quality_score":
            82,

        "quality_grade":
            "B",
    }

    return send_position_alert(
        position,
        force=True,
    )
