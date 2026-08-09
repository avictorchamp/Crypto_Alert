"""
Crypto Alert - Portfolio Monitor
Version 3.4.0

Purpose:
- Monitor assets currently held in Binance TH
- Evaluate current position against market data
- Generate HOLD / TAKE_PROFIT / PROTECT / EXIT_REVIEW
- Prepare Telegram-ready alert information
- READ ONLY: never creates orders
"""

from typing import Any, Dict, List, Optional


VERSION = "3.4.0"


# =========================================================
# CONFIG
# =========================================================

DEFAULT_RULES = {
    "take_profit_1_percent": 5.0,
    "take_profit_2_percent": 10.0,
    "stop_loss_percent": -5.0,
    "strong_profit_percent": 15.0,
    "minimum_quality": 70,
    "minimum_risk_reward": 1.0,
}


# =========================================================
# SAFE HELPERS
# =========================================================

def safe_float(
    value: Any,
    default: float = 0.0
) -> float:

    try:
        return float(value)
    except (
        TypeError,
        ValueError
    ):
        return default


def round_value(
    value: Any,
    digits: int = 4
) -> Optional[float]:

    if value is None:
        return None

    try:
        return round(
            float(value),
            digits
        )
    except (
        TypeError,
        ValueError
    ):
        return None


# =========================================================
# POSITION STATE
# =========================================================

def get_position_pnl(
    position: Dict[str, Any]
) -> Optional[float]:

    pnl = position.get(
        "unrealized_pnl_percent"
    )

    if pnl is None:
        return None

    return safe_float(
        pnl,
        0.0
    )


def get_position_quantity(
    position: Dict[str, Any]
) -> float:

    return safe_float(
        position.get(
            "quantity",
            0
        )
    )


# =========================================================
# MARKET HELPERS
# =========================================================

def get_market_regime(
    market: Dict[str, Any]
) -> str:

    regime = market.get(
        "market_regime"
    )

    if isinstance(
        regime,
        dict
    ):

        return str(
            regime.get(
                "status",
                "UNKNOWN"
            )
        ).upper()

    if regime:

        return str(
            regime
        ).upper()

    return "UNKNOWN"


def get_quality_score(
    market: Dict[str, Any]
) -> float:

    return safe_float(
        market.get(
            "quality_score",
            0
        )
    )


def get_risk_reward(
    market: Dict[str, Any]
) -> float:

    return safe_float(
        market.get(
            "risk_reward",
            0
        )
    )


def get_current_price(
    market: Dict[str, Any]
) -> float:

    return safe_float(
        market.get(
            "price",
            market.get(
                "current_price",
                0
            )
        )
    )


# =========================================================
# POSITION EVALUATION
# =========================================================

def evaluate_position(
    position: Dict[str, Any],
    market: Optional[Dict[str, Any]] = None,
    rules: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:

    if market is None:
        market = {}

    config = dict(
        DEFAULT_RULES
    )

    if rules:
        config.update(
            rules
        )

    asset = str(
        position.get(
            "asset",
            "UNKNOWN"
        )
    )

    quantity = get_position_quantity(
        position
    )

    current_price = (
        get_current_price(
            market
        )
        or safe_float(
            position.get(
                "current_price",
                0
            )
        )
    )

    average_entry = safe_float(
        position.get(
            "average_entry",
            0
        )
    )

    pnl = get_position_pnl(
        position
    )

    if pnl is None and average_entry > 0:

        if current_price > 0:

            pnl = (
                (
                    current_price
                    - average_entry
                )
                / average_entry
            ) * 100

    quality_score = get_quality_score(
        market
    )

    risk_reward = get_risk_reward(
        market
    )

    regime = get_market_regime(
        market
    )

    reasons: List[str] = []

    action = "HOLD"

    priority = "NORMAL"

    # =====================================================
    # UNKNOWN COST BASIS
    # =====================================================

    if average_entry <= 0:

        action = "MONITOR"

        priority = "NORMAL"

        reasons.append(
            "Average entry price unavailable"
        )

    # =====================================================
    # STRONG PROFIT
    # =====================================================

    elif pnl is not None and pnl >= config[
        "strong_profit_percent"
    ]:

        action = "TAKE_PROFIT"

        priority = "HIGH"

        reasons.append(
            "Position has strong unrealized profit"
        )

    # =====================================================
    # TAKE PROFIT LEVEL 2
    # =====================================================

    elif pnl is not None and pnl >= config[
        "take_profit_2_percent"
    ]:

        action = "TAKE_PROFIT"

        priority = "HIGH"

        reasons.append(
            "Take-profit level 2 reached"
        )

    # =====================================================
    # TAKE PROFIT LEVEL 1
    # =====================================================

    elif pnl is not None and pnl >= config[
        "take_profit_1_percent"
    ]:

        action = "TAKE_PROFIT"

        priority = "MEDIUM"

        reasons.append(
            "Take-profit level 1 reached"
        )

    # =====================================================
    # STOP LOSS / PROTECTION
    # =====================================================

    elif pnl is not None and pnl <= config[
        "stop_loss_percent"
    ]:

        action = "PROTECT"

        priority = "HIGH"

        reasons.append(
            "Position loss exceeded protection threshold"
        )

    # =====================================================
    # BEARISH MARKET
    # =====================================================

    if regime == "BEARISH":

        if action == "HOLD":

            action = "EXIT_REVIEW"

            priority = "HIGH"

        reasons.append(
            "Market regime is bearish"
        )

    # =====================================================
    # LOW QUALITY MARKET
    # =====================================================

    if (
        quality_score > 0
        and quality_score
        < config[
            "minimum_quality"
        ]
    ):

        reasons.append(
            "Current market quality is below threshold"
        )

        if action == "HOLD":

            action = "EXIT_REVIEW"

            priority = "MEDIUM"

    # =====================================================
    # POOR RISK / REWARD
    # =====================================================

    if (
        risk_reward > 0
        and risk_reward
        < config[
            "minimum_risk_reward"
        ]
    ):

        reasons.append(
            "Risk/reward is below minimum threshold"
        )

    # =====================================================
    # BULLISH + PROFIT
    # =====================================================

    if (
        regime == "BULLISH"
        and pnl is not None
        and pnl >= 0
        and action == "HOLD"
    ):

        reasons.append(
            "Bullish market supports holding position"
        )

    # =====================================================
    # DEFAULT HOLD
    # =====================================================

    if not reasons:

        reasons.append(
            "No exit condition detected"
        )

    return {
        "asset": asset,

        "action": action,

        "priority": priority,

        "quantity":
            round_value(
                quantity,
                12
            ),

        "average_entry":
            round_value(
                average_entry,
                12
            ),

        "current_price":
            round_value(
                current_price,
                12
            ),

        "unrealized_pnl_percent":
            round_value(
                pnl,
                4
            ),

        "market_regime":
            regime,

        "quality_score":
            round_value(
                quality_score,
                2
            ),

        "risk_reward":
            round_value(
                risk_reward,
                2
            ),

        "reasons":
            reasons,

        "read_only":
            True
    }


# =========================================================
# MONITOR ALL POSITIONS
# =========================================================

def monitor_positions(
    positions: List[Dict[str, Any]],
    market_data: Optional[Dict[str, Dict[str, Any]]] = None,
    rules: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:

    if market_data is None:
        market_data = {}

    results = []

    high_priority = []

    for position in positions:

        asset = str(
            position.get(
                "asset",
                ""
            )
        ).upper()

        market = market_data.get(
            asset,
            {}
        )

        result = evaluate_position(
            position=position,
            market=market,
            rules=rules
        )

        results.append(
            result
        )

        if result[
            "priority"
        ] == "HIGH":

            high_priority.append(
                result
            )

    return {
        "status":
            "success",

        "version":
            VERSION,

        "position_count":
            len(results),

        "high_priority_count":
            len(high_priority),

        "positions":
            results,

        "high_priority":
            high_priority,

        "read_only":
            True
    }


# =========================================================
# TELEGRAM MESSAGE
# =========================================================

def build_position_alert(
    result: Dict[str, Any]
) -> str:

    asset = result.get(
        "asset",
        "UNKNOWN"
    )

    action = result.get(
        "action",
        "HOLD"
    )

    priority = result.get(
        "priority",
        "NORMAL"
    )

    current_price = result.get(
        "current_price"
    )

    average_entry = result.get(
        "average_entry"
    )

    pnl = result.get(
        "unrealized_pnl_percent"
    )

    regime = result.get(
        "market_regime",
        "UNKNOWN"
    )

    quality = result.get(
        "quality_score"
    )

    rr = result.get(
        "risk_reward"
    )

    reasons = result.get(
        "reasons",
        []
    )

    lines = [
        "📊 PORTFOLIO MONITOR",
        "",
        f"🪙 {asset}",
        f"🎯 ACTION: {action}",
        f"⚠️ PRIORITY: {priority}",
        "",
    ]

    if current_price is not None:

        lines.append(
            f"💰 Current: {current_price}"
        )

    if average_entry is not None:

        lines.append(
            f"📌 Entry: {average_entry}"
        )

    if pnl is not None:

        pnl_icon = (
            "🟢"
            if pnl >= 0
            else "🔴"
        )

        lines.append(
            f"{pnl_icon} P/L: {pnl:.2f}%"
        )

    lines.extend(
        [
            "",
            f"📈 Regime: {regime}",
        ]
    )

    if quality is not None:

        lines.append(
            f"⭐ Quality: {quality}"
        )

    if rr is not None:

        lines.append(
            f"⚖️ R/R: {rr}"
        )

    if reasons:

        lines.extend(
            [
                "",
                "Reason:"
            ]
        )

        for reason in reasons:

            lines.append(
                f"• {reason}"
            )

    lines.extend(
        [
            "",
            "🔒 READ ONLY",
            "No automatic order will be placed."
        ]
    )

    return "\n".join(
        lines
    )


# =========================================================
# BUILD ALERTS
# =========================================================

def build_priority_alerts(
    monitored: Dict[str, Any]
) -> List[Dict[str, Any]]:

    alerts = []

    for result in monitored.get(
        "positions",
        []
    ):

        if result.get(
            "priority"
        ) != "HIGH":

            continue

        alerts.append(
            {
                "asset":
                    result.get(
                        "asset"
                    ),

                "action":
                    result.get(
                        "action"
                    ),

                "priority":
                    result.get(
                        "priority"
                    ),

                "message":
                    build_position_alert(
                        result
                    )
            }
        )

    return alerts


# =========================================================
# SIMPLE INTEGRATION FUNCTION
# =========================================================

def run_portfolio_monitor(
    portfolio_response: Dict[str, Any],
    market_data: Optional[Dict[str, Dict[str, Any]]] = None,
    rules: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:

    positions = portfolio_response.get(
        "positions",
        []
    )

    monitored = monitor_positions(
        positions=positions,
        market_data=market_data,
        rules=rules
    )

    alerts = build_priority_alerts(
        monitored
    )

    monitored[
        "alerts"
    ] = alerts

    return monitored
