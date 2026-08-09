import time

from app.crypto.binance_account import (
    signed_get,
    get_account,
    get_all_prices,
)


# =========================================================
# BINANCE TH POSITION MONITOR
# VERSION 3.4.0
#
# READ ONLY
#
# Purpose:
#   1. Detect assets currently held
#   2. Calculate approximate average entry
#   3. Calculate current P/L
#   4. Provide position information to main.py
#
# NO BUY
# NO SELL
# NO ORDER
# =========================================================


VERSION = "3.4.0"


# =========================================================
# CONFIG
# =========================================================

QUOTE_PRIORITY = [
    "THB",
    "USDT",
    "USDC",
]

IGNORED_ASSETS = {
    "THB",
    "USDT",
    "USDC",
}


# =========================================================
# HELPERS
# =========================================================

def safe_float(value, default=0.0):

    try:
        return float(value)

    except (
        TypeError,
        ValueError
    ):
        return default


def round_number(value, digits=8):

    if value is None:
        return None

    return round(
        float(value),
        digits
    )


# =========================================================
# EXCHANGE INFO
# =========================================================

def get_exchange_info():

    return signed_get(
        "/api/v1/exchangeInfo"
    )


# =========================================================
# FIND TRADING PAIR
# =========================================================

def get_symbols_for_asset(asset):

    data = get_exchange_info()

    symbols = data.get(
        "symbols",
        []
    )

    matches = []

    for item in symbols:

        if item.get(
            "status"
        ) != "TRADING":

            continue

        if item.get(
            "baseAsset"
        ) != asset:

            continue

        quote = item.get(
            "quoteAsset"
        )

        if quote not in QUOTE_PRIORITY:

            continue

        matches.append(
            {
                "symbol":
                    item.get("symbol"),

                "base_asset":
                    asset,

                "quote_asset":
                    quote
            }
        )

    matches.sort(
        key=lambda item:
            QUOTE_PRIORITY.index(
                item["quote_asset"]
            )
    )

    return matches


# =========================================================
# TRADE HISTORY
# =========================================================

def get_my_trades(
    symbol,
    limit=1000
):

    return signed_get(
        "/api/v1/myTrades",
        {
            "symbol": symbol,
            "limit": limit
        }
    )


# =========================================================
# CALCULATE POSITION
# =========================================================

def calculate_position(
    asset,
    balance,
    trades,
    quote_asset
):

    current_qty = safe_float(
        balance
    )

    if current_qty <= 0:

        return None

    remaining_qty = 0.0
    remaining_cost = 0.0

    realized_pnl = 0.0

    total_bought = 0.0
    total_sold = 0.0

    total_buy_cost = 0.0
    total_sell_value = 0.0

    sorted_trades = sorted(
        trades,
        key=lambda item:
            int(
                item.get(
                    "time",
                    0
                )
            )
    )

    for trade in sorted_trades:

        qty = safe_float(
            trade.get(
                "qty",
                0
            )
        )

        price = safe_float(
            trade.get(
                "price",
                0
            )
        )

        if qty <= 0:

            continue

        if price <= 0:

            continue

        is_buyer = bool(
            trade.get(
                "isBuyer",
                False
            )
        )

        quote_value = (
            qty * price
        )

        # =================================================
        # BUY
        # =================================================

        if is_buyer:

            remaining_qty += qty

            remaining_cost += (
                quote_value
            )

            total_bought += qty

            total_buy_cost += (
                quote_value
            )

            continue

        # =================================================
        # SELL
        # =================================================

        sell_qty = min(
            qty,
            remaining_qty
        )

        if sell_qty > 0:

            if remaining_qty > 0:

                average_cost = (
                    remaining_cost
                    / remaining_qty
                )

            else:

                average_cost = 0.0

            cost_removed = (
                sell_qty
                * average_cost
            )

            sell_value = (
                sell_qty
                * price
            )

            realized_pnl += (
                sell_value
                - cost_removed
            )

            remaining_cost -= (
                cost_removed
            )

            remaining_qty -= (
                sell_qty
            )

        total_sold += qty

        total_sell_value += (
            quote_value
        )

    history_qty = (
        remaining_qty
    )

    # =====================================================
    # No remaining trade-history quantity
    #
    # Possible reasons:
    #   - deposit
    #   - transfer
    #   - old trades unavailable
    # =====================================================

    if history_qty <= 0:

        return {
            "asset": asset,

            "quote_asset":
                quote_asset,

            "quantity":
                round_number(
                    current_qty,
                    12
                ),

            "history_quantity":
                0,

            "cost_basis":
                None,

            "average_entry":
                None,

            "realized_pnl":
                round_number(
                    realized_pnl,
                    8
                ),

            "cost_basis_status":
                "UNKNOWN",

            "reason":
                "No remaining buy quantity in trade history"
        }

    average_entry = (
        remaining_cost
        / history_qty
    )

    # =====================================================
    # Reconcile trade history with actual balance
    # =====================================================

    balance_difference = (
        current_qty
        - history_qty
    )

    tolerance = max(
        0.00000001,
        current_qty * 0.001
    )

    if abs(
        balance_difference
    ) > tolerance:

        cost_basis_status = (
            "PARTIAL"
        )

    else:

        cost_basis_status = (
            "CALCULATED"
        )

    return {
        "asset": asset,

        "quote_asset":
            quote_asset,

        "quantity":
            round_number(
                current_qty,
                12
            ),

        "history_quantity":
            round_number(
                history_qty,
                12
            ),

        "balance_difference":
            round_number(
                balance_difference,
                12
            ),

        "cost_basis":
            round_number(
                remaining_cost,
                8
            ),

        "average_entry":
            round_number(
                average_entry,
                12
            ),

        "realized_pnl":
            round_number(
                realized_pnl,
                8
            ),

        "total_bought":
            round_number(
                total_bought,
                12
            ),

        "total_sold":
            round_number(
                total_sold,
                12
            ),

        "total_buy_cost":
            round_number(
                total_buy_cost,
                8
            ),

        "total_sell_value":
            round_number(
                total_sell_value,
                8
            ),

        "cost_basis_status":
            cost_basis_status
    }


# =========================================================
# GET CURRENT POSITIONS
# =========================================================

def get_positions():

    account = get_account()

    balances = account.get(
        "balances",
        []
    )

    prices = get_all_prices()

    positions = []

    errors = []

    # =====================================================
    # Scan actual account balances
    # =====================================================

    for balance in balances:

        asset = balance.get(
            "asset"
        )

        if not asset:

            continue

        if asset in IGNORED_ASSETS:

            continue

        free = safe_float(
            balance.get(
                "free",
                0
            )
        )

        locked = safe_float(
            balance.get(
                "locked",
                0
            )
        )

        quantity = (
            free + locked
        )

        if quantity <= 0:

            continue

        # =================================================
        # Find trading pair
        # =================================================

        try:

            candidates = (
                get_symbols_for_asset(
                    asset
                )
            )

        except Exception as e:

            errors.append(
                {
                    "asset": asset,
                    "stage":
                        "exchange_info",
                    "error": str(e)
                }
            )

            positions.append(
                {
                    "asset": asset,
                    "quantity": quantity,
                    "status":
                        "PAIR_LOOKUP_ERROR",
                    "error": str(e)
                }
            )

            continue

        if not candidates:

            positions.append(
                {
                    "asset": asset,

                    "quantity":
                        round_number(
                            quantity,
                            12
                        ),

                    "status":
                        "NO_TRADING_PAIR",

                    "cost_basis_status":
                        "UNKNOWN"
                }
            )

            continue

        selected = candidates[0]

        symbol = selected[
            "symbol"
        ]

        quote_asset = selected[
            "quote_asset"
        ]

        # =================================================
        # Trade history
        # =================================================

        try:

            trades = get_my_trades(
                symbol
            )

        except Exception as e:

            errors.append(
                {
                    "asset": asset,
                    "symbol": symbol,
                    "stage":
                        "trade_history",
                    "error": str(e)
                }
            )

            positions.append(
                {
                    "asset": asset,

                    "quantity":
                        round_number(
                            quantity,
                            12
                        ),

                    "symbol":
                        symbol,

                    "quote_asset":
                        quote_asset,

                    "status":
                        "TRADE_HISTORY_ERROR",

                    "cost_basis_status":
                        "UNKNOWN",

                    "error":
                        str(e)
                }
            )

            continue

        # =================================================
        # Calculate cost basis
        # =================================================

        position = calculate_position(
            asset=asset,

            balance=quantity,

            trades=trades,

            quote_asset=quote_asset
        )

        if position is None:

            continue

        position[
            "symbol"
        ] = symbol

        # =================================================
        # Current price
        # =================================================

        current_price = prices.get(
            symbol
        )

        if current_price is None:

            position[
                "status"
            ] = "PRICE_UNAVAILABLE"

            positions.append(
                position
            )

            continue

        position[
            "current_price"
        ] = round_number(
            current_price,
            12
        )

        # =================================================
        # P/L
        # =================================================

        average_entry = (
            position.get(
                "average_entry"
            )
        )

        if (
            average_entry is not None
            and average_entry > 0
        ):

            pnl_percent = (
                (
                    current_price
                    - average_entry
                )
                / average_entry
            ) * 100

            unrealized_pnl = (
                (
                    current_price
                    - average_entry
                )
                * quantity
            )

            position[
                "unrealized_pnl_percent"
            ] = round(
                pnl_percent,
                4
            )

            position[
                "unrealized_pnl"
            ] = round(
                unrealized_pnl,
                8
            )

            position[
                "market_value"
            ] = round(
                quantity
                * current_price,
                8
            )

        else:

            position[
                "unrealized_pnl_percent"
            ] = None

            position[
                "unrealized_pnl"
            ] = None

            position[
                "market_value"
            ] = round(
                quantity
                * current_price,
                8
            )

        # =================================================
        # Position state
        # =================================================

        pnl = position.get(
            "unrealized_pnl_percent"
        )

        if pnl is None:

            position[
                "position_state"
            ] = "MONITOR"

        elif pnl >= 10:

            position[
                "position_state"
            ] = "PROFIT_10_PLUS"

        elif pnl >= 5:

            position[
                "position_state"
            ] = "PROFIT_5_PLUS"

        elif pnl >= 0:

            position[
                "position_state"
            ] = "PROFIT"

        elif pnl >= -5:

            position[
                "position_state"
            ] = "LOSS"

        else:

            position[
                "position_state"
            ] = "STOP_RISK"

        position[
            "status"
        ] = "ACTIVE"

        positions.append(
            position
        )

    # =====================================================
    # Sort highest market value first
    # =====================================================

    positions.sort(
        key=lambda item:
            item.get(
                "market_value",
                0
            ) or 0,

        reverse=True
    )

    return {
        "status":
            "success",

        "account_type":
            "READ_ONLY",

        "version":
            VERSION,

        "position_count":
            len(positions),

        "positions":
            positions,

        "errors":
            errors
    }
