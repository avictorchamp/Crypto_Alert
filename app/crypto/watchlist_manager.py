"""
Crypto Alert - Watchlist Manager
Version 3.8.0

Combines:
1. Dynamic market universe
2. Watchlist memory
3. Portfolio holdings

Rules:
- Dynamic coins are remembered for 12 hours
- Strong setups are remembered for 24 hours
- Held portfolio coins never expire while held
- Sold coins return to normal watchlist memory
- No automatic trading
"""

from typing import Any, Dict, List

from app.crypto.watchlist_memory import (
    remember_market,
    remember_portfolio,
    get_watchlist,
    get_watchlist_details,
    get_status,
    cleanup_expired,
)


VERSION = "3.8.0"


# =========================================================
# NORMALIZE MARKET DATA
# =========================================================

def normalize_market_data(
    market_data: Any,
) -> List[Dict[str, Any]]:

    if isinstance(
        market_data,
        list,
    ):

        return market_data

    if isinstance(
        market_data,
        dict,
    ):

        data = market_data.get(
            "data",
            []
        )

        if isinstance(
            data,
            list,
        ):

            return data

    return []


# =========================================================
# NORMALIZE PORTFOLIO
# =========================================================

def normalize_positions(
    portfolio_response: Any,
) -> List[Dict[str, Any]]:

    if not isinstance(
        portfolio_response,
        dict,
    ):

        return []

    # ---------------------------------------------
    # Direct positions
    # ---------------------------------------------

    positions = portfolio_response.get(
        "positions"
    )

    if isinstance(
        positions,
        list,
    ):

        return positions

    # ---------------------------------------------
    # Nested portfolio response
    # ---------------------------------------------

    portfolio = portfolio_response.get(
        "portfolio"
    )

    if isinstance(
        portfolio,
        dict,
    ):

        positions = portfolio.get(
            "positions"
        )

        if isinstance(
            positions,
            list,
        ):

            return positions

        assets = portfolio.get(
            "assets"
        )

        if isinstance(
            assets,
            list,
        ):

            result = []

            for asset in assets:

                if not isinstance(
                    asset,
                    dict,
                ):

                    continue

                total = float(
                    asset.get(
                        "total",
                        0
                    ) or 0
                )

                if total <= 0:

                    continue

                result.append(
                    {
                        "asset":
                            asset.get(
                                "asset"
                            ),

                        "quantity":
                            total,

                        "current_price":
                            asset.get(
                                "price_usdt"
                            ),
                    }
                )

            return result

    return []


# =========================================================
# UPDATE MEMORY
# =========================================================

def update_watchlist_memory(
    market_data: Any,
    portfolio_response: Any = None,
) -> Dict[str, Any]:

    market = normalize_market_data(
        market_data
    )

    positions = normalize_positions(
        portfolio_response
    )

    # ---------------------------------------------
    # Remember current dynamic market
    # ---------------------------------------------

    remember_market(
        market
    )

    # ---------------------------------------------
    # Remember portfolio holdings
    # ---------------------------------------------

    remember_portfolio(
        positions
    )

    # ---------------------------------------------
    # Remove expired entries
    # ---------------------------------------------

    cleanup_expired()

    details = get_watchlist_details()

    return {

        "status":
            "success",

        "version":
            VERSION,

        "dynamic_market_count":
            len(market),

        "portfolio_position_count":
            len(positions),

        "watchlist_count":
            len(details),

        "watchlist":
            details,

        "coins":
            get_watchlist(),

        "read_only":
            True,
    }


# =========================================================
# BUILD MONITOR UNIVERSE
# =========================================================

def build_monitor_universe(
    market_data: Any,
    portfolio_response: Any = None,
) -> List[str]:

    result = update_watchlist_memory(
        market_data=market_data,
        portfolio_response=portfolio_response,
    )

    coins = result.get(
        "coins",
        []
    )

    return sorted(
        set(
            str(coin).upper()
            for coin in coins
            if coin
        )
    )


# =========================================================
# GET STATUS
# =========================================================

def watchlist_status() -> Dict[str, Any]:

    return get_status()


# =========================================================
# CHECK COIN
# =========================================================

def is_coin_monitored(
    coin: str,
) -> bool:

    target = str(
        coin
    ).upper().strip()

    return target in set(
        get_watchlist()
    )


# =========================================================
# PORTFOLIO COINS
# =========================================================

def get_portfolio_coins() -> List[str]:

    details = get_watchlist_details()

    result = []

    for item in details:

        if item.get(
            "portfolio_held"
        ):

            coin = item.get(
                "coin"
            )

            if coin:

                result.append(
                    str(
                        coin
                    ).upper()
                )

    return sorted(
        set(result)
    )


# =========================================================
# STRONG SETUPS
# =========================================================

def get_strong_setup_coins() -> List[str]:

    details = get_watchlist_details()

    result = []

    for item in details:

        if item.get(
            "strong_setup"
        ):

            coin = item.get(
                "coin"
            )

            if coin:

                result.append(
                    str(
                        coin
                    ).upper()
                )

    return sorted(
        set(result)
    )


# =========================================================
# SUMMARY
# =========================================================

def get_watchlist_summary() -> Dict[str, Any]:

    details = get_watchlist_details()

    portfolio = []

    strong = []

    normal = []

    for item in details:

        coin = item.get(
            "coin"
        )

        if not coin:

            continue

        if item.get(
            "portfolio_held"
        ):

            portfolio.append(
                coin
            )

        elif item.get(
            "strong_setup"
        ):

            strong.append(
                coin
            )

        else:

            normal.append(
                coin
            )

    return {

        "status":
            "success",

        "version":
            VERSION,

        "total":
            len(details),

        "portfolio":
            sorted(portfolio),

        "strong_setup":
            sorted(strong),

        "normal":
            sorted(normal),

        "read_only":
            True,
    }
