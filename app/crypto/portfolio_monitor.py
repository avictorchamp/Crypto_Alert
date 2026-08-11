"""
Crypto Alert - Portfolio Monitor
Version 3.6.0

Purpose:
- Monitor assets currently held in Binance TH
- Evaluate current position against market data
- Track position profit protection
- Generate HOLD / TAKE_PROFIT / PROTECT / EXIT_REVIEW
- Prepare Telegram-ready alert information
- READ ONLY: never creates orders

Important:
- No BUY
- No SELL
- No order execution
- User remains responsible for trading decisions
"""

from typing import Any, Dict, List, Optional
import time


VERSION = "3.6.0"


# =========================================================
# CONFIG
# =========================================================

DEFAULT_RULES = {

    # Normal profit levels
    "take_profit_1_percent": 5.0,
    "take_profit_2_percent": 10.0,

    # Hard protection
    "stop_loss_percent": -5.0,

    # Strong profit
    "strong_profit_percent": 15.0,

    # Quality filters
    "minimum_quality": 70,
    "minimum_risk_reward": 1.0,

    # -----------------------------------------------------
    # TRAILING PROTECTION
    # -----------------------------------------------------

    # Start trailing protection after this profit
    "trailing_start_percent": 8.0,

    # If profit falls this percentage from peak profit,
    # trigger protection.
    "trailing_drawdown_percent": 3.0,

    # Emergency protection after very strong profit
    "strong_profit_protection_percent": 20.0,
}


# =========================================================
# RUNTIME STATE
#
# NOTE:
# Render may restart the service, therefore this state
# should be treated as temporary protection memory.
#
# Binance remains the source of truth for actual holdings.
# =========================================================

_position_state: Dict[str, Dict[str, Any]] = {}


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


def optional_float(
    value: Any
) -> Optional[float]:

    if value is None:

        return None

    try:

        return float(value)

    except (
        TypeError,
        ValueError
    ):

        return None


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
# POSITION IDENTIFIER
# =========================================================

def get_position_key(
    position: Dict[str, Any]
) -> str:

    asset = str(
        position.get(
            "asset",
            "UNKNOWN"
        )
    ).upper()

    return asset


# =========================================================
# POSITION DATA
# =========================================================

def get_position_pnl(
    position: Dict[str, Any]
) -> Optional[float]:

    pnl = optional_float(
        position.get(
            "unrealized_pnl_percent"
        )
    )

    if pnl is not None:

        return pnl

    current_price = optional_float(
        position.get(
            "current_price"
        )
    )

    average_entry = optional_float(
        position.get(
            "average_entry"
        )
    )

    if (
        current_price is not None
        and average_entry is not None
        and average_entry > 0
    ):

        return (
            (
                current_price
                - average_entry
            )
            / average_entry
        ) * 100

    return None


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
    position: Dict[str, Any],
    market: Dict[str, Any]
) -> float:

    market_price = optional_float(
        market.get(
            "price"
        )
    )

    if market_price is not None:

        return market_price

    return safe_float(
        position.get(
            "current_price",
            0
        )
    )


# =========================================================
# PEAK PROFIT TRACKING
# =========================================================

def update_peak_state(
    position: Dict[str, Any],
    current_price: float,
    pnl: Optional[float]
) -> Dict[str, Any]:

    key = get_position_key(
        position
    )

    state = _position_state.get(
        key
    )

    if state is None:

        state = {

            "first_seen":
                time.time(),

            "peak_price":
                current_price
                if current_price > 0
                else None,

            "peak_pnl_percent":
                pnl
                if pnl is not None
                else 0.0,

            "last_price":
                current_price,

            "last_pnl_percent":
                pnl,

            "peak_updated_at":
                time.time(),
        }

        _position_state[
            key
        ] = state

        return state

    # -----------------------------------------------------
    # Update peak price
    # -----------------------------------------------------

    peak_price = state.get(
        "peak_price"
    )

    if (
        current_price > 0
        and (
            peak_price is None
            or current_price > peak_price
        )
    ):

        state[
            "peak_price"
        ] = current_price

        state[
            "peak_updated_at"
        ] = time.time()

    # -----------------------------------------------------
    # Update peak P/L
    # -----------------------------------------------------

    peak_pnl = safe_float(
        state.get(
            "peak_pnl_percent",
            0
        )
    )

    if (
        pnl is not None
        and pnl > peak_pnl
    ):

        state[
            "peak_pnl_percent"
        ] = pnl

        state[
            "peak_updated_at"
        ] = time.time()

    state[
        "last_price"
    ] = current_price

    state[
        "last_pnl_percent"
    ] = pnl

    return state


# =========================================================
# TRAILING PROTECTION
# =========================================================

def evaluate_trailing_protection(
    pnl: Optional[float],
    peak_pnl: Optional[float],
    rules: Dict[str, Any]
) -> Dict[str, Any]:

    if (
        pnl is None
        or peak_pnl is None
    ):

        return {
            "active":
                False,

            "triggered":
                False,

            "drawdown":
                None,

            "reason":
                "P/L data unavailable",
        }

    trailing_start = safe_float(
        rules.get(
            "trailing_start_percent",
            8.0
        )
    )

    trailing_drawdown = safe_float(
        rules.get(
            "trailing_drawdown_percent",
            3.0
        )
    )

    # -----------------------------------------------------
    # Trailing not started yet
    # -----------------------------------------------------

    if peak_pnl < trailing_start:

        return {
            "active":
                False,

            "triggered":
                False,

            "drawdown":
                round(
                    peak_pnl - pnl,
                    4
                ),

            "peak_pnl":
                round(
                    peak_pnl,
                    4
                ),

            "reason":
                "Trailing protection not active yet",
        }

    drawdown = (
        peak_pnl - pnl
    )

    if drawdown >= trailing_drawdown:

        return {
            "active":
                True,

            "triggered":
                True,

            "drawdown":
                round(
                    drawdown,
                    4
                ),

            "peak_pnl":
                round(
                    peak_pnl,
                    4
                ),

            "reason":
                "Profit retraced from peak",
        }

    return {
        "active":
            True,

        "triggered":
            False,

        "drawdown":
            round(
                drawdown,
                4
            ),

        "peak_pnl":
            round(
                peak_pnl,
                4
            ),

        "reason":
            "Trailing protection active",
    }


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
    ).upper()

    quantity = get_position_quantity(
        position
    )

    current_price = get_current_price(
        position,
        market
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

    quality_score = get_quality_score(
        market
    )

    risk_reward = get_risk_reward(
        market
    )

    regime = get_market_regime(
        market
    )

    # -----------------------------------------------------
    # Update peak state
    # -----------------------------------------------------

    state = update_peak_state(
        position=position,
        current_price=current_price,
        pnl=pnl
    )

    peak_price = state.get(
        "peak_price"
    )

    peak_pnl = state.get(
        "peak_pnl_percent"
    )

    trailing = evaluate_trailing_protection(
        pnl=pnl,
        peak_pnl=peak_pnl,
        rules=config
    )

    reasons: List[str] = []

    action = "HOLD"

    priority = "NORMAL"

    # =====================================================
    # UNKNOWN ENTRY
    # =====================================================

    if average_entry <= 0:

        action = "MONITOR"

        priority = "NORMAL"

        reasons.append(
            "Average entry price unavailable"
        )

    # =====================================================
    # EMERGENCY LOSS
    # =====================================================

    elif (
        pnl is not None
        and pnl <= -10
    ):

        action = "EXIT_REVIEW"

        priority = "CRITICAL"

        reasons.append(
            "Position loss reached -10%"
        )

    # =====================================================
    # HARD STOP
    # =====================================================

    elif (
        pnl is not None
        and pnl <= config[
            "stop_loss_percent"
        ]
    ):

        action = "PROTECT"

        priority = "HIGH"

        reasons.append(
            "Position loss exceeded protection threshold"
        )

    # =====================================================
    # TRAILING PROTECTION
    # =====================================================

    elif trailing[
        "triggered"
    ]:

        action = "PROTECT"

        priority = "HIGH"

        reasons.append(
            "Profit retraced from peak"
        )

    # =====================================================
    # STRONG PROFIT
    # =====================================================

    elif (
        pnl is not None
        and pnl >= config[
            "strong_profit_percent"
        ]
    ):

        action = "TAKE_PROFIT"

        priority = "HIGH"

        reasons.append(
            "Position has strong unrealized profit"
        )

    # =====================================================
    # TAKE PROFIT 2
    # =====================================================

    elif (
        pnl is not None
        and pnl >= config[
            "take_profit_2_percent"
        ]
    ):

        action = "TAKE_PROFIT"

        priority = "HIGH"

        reasons.append(
            "Take-profit level 2 reached"
        )

    # =====================================================
    # TAKE PROFIT 1
    # =====================================================

    elif (
        pnl is not None
        and pnl >= config[
            "take_profit_1_percent"
        ]
    ):

        action = "TAKE_PROFIT"

        priority = "MEDIUM"

        reasons.append(
            "Take-profit level 1 reached"
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
    # LOW QUALITY
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
    # RISK / REWARD
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
    # BULLISH HOLD
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
    # DEFAULT
    # =====================================================

    if not reasons:

        reasons.append(
            "No immediate action required"
        )

    # =====================================================
    # TRAILING STATUS
    # =====================================================

    if trailing[
        "active"
    ]:

        trailing_status = (
            "ACTIVE"
            if not trailing[
                "triggered"
            ]
            else "TRIGGERED"
        )

    else:

        trailing_status = "INACTIVE"

    return {

        "asset":
            asset,

        "action":
            action,

        "priority":
            priority,

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

        # -------------------------------------------------
        # PEAK TRACKING
        # -------------------------------------------------

        "peak_price":
            round_value(
                peak_price,
                12
            ),

        "peak_pnl_percent":
            round_value(
                peak_pnl,
                4
            ),

        "profit_drawdown_percent":
            round_value(
                trailing.get(
                    "drawdown"
                ),
                4
            ),

        # -------------------------------------------------
        # TRAILING
        # -------------------------------------------------

        "trailing_protection":
            {
                "status":
                    trailing_status,

                "active":
                    trailing.get(
                        "active",
                        False
                    ),

                "triggered":
                    trailing.get(
                        "triggered",
                        False
                    ),

                "peak_pnl_percent":
                    round_value(
                        trailing.get(
                            "peak_pnl"
                        ),
                        4
                    ),

                "drawdown_percent":
                    round_value(
                        trailing.get(
                            "drawdown"
                        ),
                        4
                    ),

                "reason":
                    trailing.get(
                        "reason"
                    ),
            },

        # -------------------------------------------------
        # MARKET
        # -------------------------------------------------

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
# MONITOR POSITIONS
# =========================================================

def monitor_positions(
    positions: List[Dict[str, Any]],
    market_data: Optional[
        Dict[str, Dict[str, Any]]
    ] = None,
    rules: Optional[
        Dict[str, Any]
    ] = None
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

        if result.get(
            "priority"
        ) in {
            "HIGH",
            "CRITICAL"
        }:

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

    peak_pnl = result.get(
        "peak_pnl_percent"
    )

    drawdown = result.get(
        "profit_drawdown_percent"
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

    trailing = result.get(
        "trailing_protection",
        {}
    )

    reasons = result.get(
        "reasons",
        []
    )

    if action == "TAKE_PROFIT":

        icon = "🟢"

    elif action == "PROTECT":

        icon = "🟠"

    elif action == "EXIT_REVIEW":

        icon = "🔴"

    else:

        icon = "🟡"

    lines = [

        f"{icon} PORTFOLIO ALERT",

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

        lines.append(
            f"📊 P/L: {pnl:.2f}%"
        )

    if peak_pnl is not None:

        lines.append(
            f"🚀 Peak P/L: {peak_pnl:.2f}%"
        )

    if drawdown is not None:

        lines.append(
            f"📉 Profit Drawdown: {drawdown:.2f}%"
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

    if trailing:

        lines.extend(
            [
                "",
                "🛡️ TRAILING PROTECTION",
                f"Status: {trailing.get('status', 'INACTIVE')}",
            ]
        )

    if reasons:

        lines.extend(
            [
                "",
                "🧠 Reason:"
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
            "No automatic BUY/SELL order."
        ]
    )

    return "\n".join(
        lines
    )


# =========================================================
# BUILD PRIORITY ALERTS
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
        ) not in {
            "HIGH",
            "CRITICAL"
        }:

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
# MAIN INTEGRATION
# =========================================================

def run_portfolio_monitor(
    portfolio_response: Dict[str, Any],
    market_data: Optional[
        Dict[str, Dict[str, Any]]
    ] = None,
    rules: Optional[
        Dict[str, Any]
    ] = None
) -> Dict[str, Any]:

    positions = portfolio_response.get(
        "positions",
        []
    )

    if not isinstance(
        positions,
        list
    ):

        positions = []

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


# =========================================================
# RESET POSITION STATE
#
# Useful when an asset is no longer held.
# =========================================================

def cleanup_positions(
    current_assets: List[str]
) -> None:

    normalized = {
        str(asset).upper()
        for asset in current_assets
    }

    stale_assets = [

        asset

        for asset in _position_state

        if asset not in normalized
    ]

    for asset in stale_assets:

        del _position_state[
            asset
        ]


# =========================================================
# DEBUG STATE
# =========================================================

def get_tracking_state() -> Dict[str, Any]:

    result = {}

    for asset, state in _position_state.items():

        result[
            asset
        ] = {

            "peak_price":
                state.get(
                    "peak_price"
                ),

            "peak_pnl_percent":
                state.get(
                    "peak_pnl_percent"
                ),

            "last_price":
                state.get(
                    "last_price"
                ),

            "last_pnl_percent":
                state.get(
                    "last_pnl_percent"
                ),

            "peak_updated_at":
                state.get(
                    "peak_updated_at"
                ),
        }

    return result
