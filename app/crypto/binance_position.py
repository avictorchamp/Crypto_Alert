import time

from app.crypto.binance_account import (
    signed_get,
    get_account,
    get_all_prices,
)


# =========================================================
# BINANCE TH POSITION MONITOR
# READ ONLY
# =========================================================

QUOTE_PRIORITY = [
    "THB",
    "USDT",
    "USDC",
]


# =========================================================
# EXCHANGE INFO
# =========================================================

def get_exchange_info():

    return signed_get(
        "/api/v1/exchangeInfo"
    )


def get_symbols_for_asset(asset):

    data = get_exchange_info()

    symbols = data.get(
        "symbols",
        []
    )

    matches = []

    for item in symbols:

        if item.get("status") != "TRADING":
            continue

        if item.get("baseAsset") != asset:
            continue

        quote = item.get(
            "quoteAsset"
        )

        if quote not in QUOTE_PRIORITY:
            continue

        matches.append(
            {
                "symbol": item.get("symbol"),
                "base_asset": asset,
                "quote_asset": quote
            }
        )

    # Preferred quote first.
    matches.sort(
        key=lambda x: (
            QUOTE_PRIORITY.index(
                x["quote_asset"]
            )
            if x["quote_asset"]
            in QUOTE_PRIORITY
            else 999
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
# CALCULATE COST BASIS
# =========================================================

def calculate_position(
    asset,
    balance,
    trades,
    quote_asset
):

    try:

        current_qty = float(
            balance
        )

    except (
        TypeError,
        ValueError
    ):

        current_qty = 0.0

    if current_qty <= 0:

        return None

    # Average-cost accounting.
    remaining_qty = 0.0
    remaining_cost = 0.0

    realized_pnl = 0.0

    total_bought = 0.0
    total_sold = 0.0

    total_buy_cost = 0.0
    total_sell_value = 0.0

    sorted_trades = sorted(
        trades,
        key=lambda x: (
            int(
                x.get(
                    "time",
                    0
                )
            )
        )
    )

    for trade in sorted_trades:

        try:

            qty = float(
                trade.get(
                    "qty",
                    0
                )
            )

            price = float(
                trade.get(
                    "price",
                    0
                )
            )

        except (
            TypeError,
            ValueError
        ):

            continue

        if qty <= 0 or price <= 0:
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

        # -------------------------------------------------
        # BUY
        # -------------------------------------------------

        if is_buyer:

            remaining_qty += qty

            remaining_cost += (
                quote_value
            )

            total_bought += qty

            total_buy_cost += (
                quote_value
            )

        # -------------------------------------------------
        # SELL
        # -------------------------------------------------

        else:

            sell_qty = min(
                qty,
                remaining_qty
            )

            if sell_qty > 0:

                average_cost = (
                    remaining_cost
                    / remaining_qty
                )

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

    # -----------------------------------------------------
    # Reconcile against actual Binance balance.
    #
    # Deposits / transfers can cause the trade-history
    # quantity to differ from actual balance.
    # -----------------------------------------------------

    history_qty = remaining_qty

    if history_qty <= 0:

        return {
            "asset": asset,
            "quote_asset": quote_asset,
            "quantity": current_qty,
            "cost_basis": None,
            "average_entry": None,
            "realized_pnl": round(
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

    # If Binance balance differs materially from
    # calculated trade quantity, mark it.
    balance_difference = (
        current_qty
        - history_qty
    )

    if abs(
        balance_difference
    ) > max(
        0.00000001,
        current_qty * 0.001
    ):

        cost_basis_status = (
            "PARTIAL"
        )

    else:

        cost_basis_status = (
            "CALCULATED"
        )

    return {
        "asset": asset,
        "quote_asset": quote_asset,
        "quantity": current_qty,
        "history_quantity": round(
            history_qty,
            12
        ),
        "balance_difference": round(
            balance_difference,
            12
        ),
        "cost_basis": round(
            remaining_cost,
            8
        ),
        "average_entry": round(
            average_entry,
            12
        ),
        "realized_pnl": round(
            realized_pnl,
            8
        ),
        "total_bought": round(
            total_bought,
            12
        ),
        "total_sold": round(
            total_sold,
            12
        ),
        "total_buy_cost": round(
            total_buy_cost,
            8
        ),
        "total_sell_value": round(
            total_sell_value,
            8
        ),
        "cost_basis_status":
            cost_basis_status
    }


# =========================================================
# POSITION SNAPSHOT
# =========================================================

def get_positions():

    account = get_account()

    balances = account.get(
        "balances",
        []
    )

    prices = get_all_prices()

    positions = []

    for balance in balances:

        asset = balance.get(
            "asset"
        )

        if not asset:
            continue

        try:

            free = float(
                balance.get(
                    "free",
                    0
                )
            )

            locked = float(
                balance.get(
                    "locked",
                    0
                )
            )

        except (
            TypeError,
            ValueError
        ):

            continue

        quantity = (
            free + locked
        )

        # Ignore fiat / stable balances
        # that are not positions.
        if asset in {
            "THB",
            "USDT",
            "USDC"
        }:

            continue

        if quantity <= 0:
            continue

        symbol_candidates = (
            get_symbols_for_asset(
                asset
            )
        )

        if not symbol_candidates:

            positions.append(
                {
                    "asset": asset,
                    "quantity": quantity,
                    "status":
                        "NO_TRADING_PAIR"
                }
            )

            continue

        selected = (
            symbol_candidates[0]
        )

        symbol = selected[
            "symbol"
        ]

        quote_asset = selected[
            "quote_asset"
        ]

        try:

            trades = get_my_trades(
                symbol
            )

        except Exception as e:

            positions.append(
                {
                    "asset": asset,
                    "quantity": quantity,
                    "symbol": symbol,
                    "quote_asset":
                        quote_asset,
                    "status":
                        "TRADE_HISTORY_ERROR",
                    "error": str(e)
                }
            )

            continue

        position = calculate_position(
            asset=asset,
            balance=quantity,
            trades=trades,
            quote_asset=quote_asset
        )

        if position is None:
            continue

        # -------------------------------------------------
        # Current market price
        # -------------------------------------------------

        current_price = prices.get(
            symbol
        )

        if current_price is not None:

            position[
                "symbol"
            ] = symbol

            position[
                "current_price"
            ] = current_price

            if position.get(
                "average_entry"
            ):

                entry = float(
                    position[
                        "average_entry"
                    ]
                )

                if entry > 0:

                    pnl_percent = (
                        (
                            current_price
                            - entry
                        )
                        / entry
                    ) * 100

                    position[
                        "unrealized_pnl_percent"
                    ] = round(
                        pnl_percent,
                        4
                    )

                    position[
                        "market_value"
                    ] = round(
                        quantity
                        * current_price,
                        8
                    )

        positions.append(
            position
        )

    return {
        "status": "success",
        "account_type":
            "READ_ONLY",
        "positions": positions,
        "position_count":
            len(positions)
    }
