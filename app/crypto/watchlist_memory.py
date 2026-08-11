"""
Crypto Alert - Watchlist Memory
Version 3.7.0

Purpose:
- Remember coins that recently entered the dynamic universe
- Keep promising coins monitored after they leave Top N
- Prevent missed opportunities caused by ranking changes
- Keep held portfolio assets permanently monitored
- READ ONLY
"""

import time
from typing import Dict, List, Any


VERSION = "3.7.0"


# =========================================================
# CONFIG
# =========================================================

# Normal watchlist memory
WATCHLIST_TTL_SECONDS = 12 * 60 * 60
# 12 hours

# If a coin has a strong setup, keep it longer.
STRONG_SETUP_TTL_SECONDS = 24 * 60 * 60
# 24 hours

# Portfolio coins are never removed by TTL.
PORTFOLIO_TTL_SECONDS = None


# =========================================================
# MEMORY
# =========================================================

_watchlist: Dict[str, Dict[str, Any]] = {}


# =========================================================
# TIME
# =========================================================

def now() -> float:

    return time.time()


# =========================================================
# NORMALIZE
# =========================================================

def normalize_coin(
    coin: Any
) -> str:

    return str(
        coin
    ).upper().strip()


# =========================================================
# ADD / UPDATE COIN
# =========================================================

def remember_coin(
    coin: str,
    source: str = "DYNAMIC",
    quality_score: float = 0,
    signal: str = "WAIT",
    market_regime: str = "UNKNOWN",
    reason: str = "",
    strong_setup: bool = False,
    portfolio_held: bool = False,
) -> Dict[str, Any]:

    coin = normalize_coin(
        coin
    )

    if not coin:

        return {}

    timestamp = now()

    existing = _watchlist.get(
        coin
    )

    # -----------------------------------------------------
    # Existing coin
    # -----------------------------------------------------

    if existing:

        existing[
            "last_seen"
        ] = timestamp

        existing[
            "last_quality_score"
        ] = quality_score

        existing[
            "last_signal"
        ] = signal

        existing[
            "last_market_regime"
        ] = market_regime

        if reason:

            existing[
                "last_reason"
            ] = reason

        # -------------------------------------------------
        # Upgrade source
        # -------------------------------------------------

        if source == "PORTFOLIO":

            existing[
                "source"
            ] = "PORTFOLIO"

        elif existing.get(
            "source"
        ) != "PORTFOLIO":

            existing[
                "source"
            ] = source

        # -------------------------------------------------
        # Portfolio assets never expire
        # -------------------------------------------------

        if portfolio_held:

            existing[
                "portfolio_held"
            ] = True

            existing[
                "expires_at"
            ] = None

        # -------------------------------------------------
        # Strong setup extends memory
        # -------------------------------------------------

        elif strong_setup:

            existing[
                "strong_setup"
            ] = True

            existing[
                "expires_at"
            ] = (
                timestamp
                + STRONG_SETUP_TTL_SECONDS
            )

        return existing

    # -----------------------------------------------------
    # New coin
    # -----------------------------------------------------

    if portfolio_held:

        expires_at = None

    elif strong_setup:

        expires_at = (
            timestamp
            + STRONG_SETUP_TTL_SECONDS
        )

    else:

        expires_at = (
            timestamp
            + WATCHLIST_TTL_SECONDS
        )

    entry = {

        "coin":
            coin,

        "source":
            source,

        "first_seen":
            timestamp,

        "last_seen":
            timestamp,

        "expires_at":
            expires_at,

        "strong_setup":
            strong_setup,

        "portfolio_held":
            portfolio_held,

        "last_quality_score":
            quality_score,

        "last_signal":
            signal,

        "last_market_regime":
            market_regime,

        "last_reason":
            reason,
    }

    _watchlist[
        coin
    ] = entry

    return entry


# =========================================================
# REMEMBER MARKET SCAN
# =========================================================

def remember_market(
    market_data: List[Dict[str, Any]]
) -> None:

    for item in market_data:

        if not isinstance(
            item,
            dict
        ):

            continue

        coin = item.get(
            "coin"
        )

        if not coin:

            continue

        quality = float(
            item.get(
                "quality_score",
                0
            ) or 0
        )

        signal = item.get(
            "signal",
            "WAIT"
        )

        regime = item.get(
            "market_regime",
            "UNKNOWN"
        )

        if isinstance(
            regime,
            dict
        ):

            regime = regime.get(
                "status",
                "UNKNOWN"
            )

        reasons = item.get(
            "reason",
            []
        )

        reason = ", ".join(
            str(x)
            for x in reasons
        )

        # -------------------------------------------------
        # Strong setup
        # -------------------------------------------------

        strong_setup = (
            quality >= 75
            and signal in {
                "BUY SETUP",
                "STRONG BUY",
            }
            and str(
                regime
            ).upper() == "BULLISH"
        )

        remember_coin(

            coin=coin,

            source="DYNAMIC",

            quality_score=quality,

            signal=signal,

            market_regime=str(
                regime
            ).upper(),

            reason=reason,

            strong_setup=strong_setup,
        )


# =========================================================
# REMEMBER PORTFOLIO
# =========================================================

def remember_portfolio(
    positions: List[Dict[str, Any]]
) -> None:

    active_assets = set()

    for position in positions:

        if not isinstance(
            position,
            dict
        ):

            continue

        coin = position.get(
            "asset"
        )

        if not coin:

            continue

        coin = normalize_coin(
            coin
        )

        active_assets.add(
            coin
        )

        remember_coin(

            coin=coin,

            source="PORTFOLIO",

            quality_score=0,

            signal="HELD",

            market_regime="UNKNOWN",

            reason="Asset currently held",

            portfolio_held=True,
        )

    # -----------------------------------------------------
    # Remove portfolio flag when asset is sold.
    #
    # IMPORTANT:
    # We do NOT immediately delete the coin.
    # It remains in normal watchlist memory.
    # -----------------------------------------------------

    for coin, entry in _watchlist.items():

        if entry.get(
            "portfolio_held"
        ):

            if coin not in active_assets:

                entry[
                    "portfolio_held"
                ] = False

                entry[
                    "source"
                ] = "WATCHLIST"

                entry[
                    "last_reason"
                ] = (
                    "No longer held; "
                    "returned to watchlist"
                )

                # Give it a fresh 12-hour memory.
                entry[
                    "expires_at"
                ] = (
                    now()
                    + WATCHLIST_TTL_SECONDS
                )


# =========================================================
# CLEAN EXPIRED
# =========================================================

def cleanup_expired() -> None:

    timestamp = now()

    expired = []

    for coin, entry in _watchlist.items():

        # Portfolio assets never expire.
        if entry.get(
            "portfolio_held"
        ):

            continue

        expires_at = entry.get(
            "expires_at"
        )

        if (
            expires_at is not None
            and timestamp >= expires_at
        ):

            expired.append(
                coin
            )

    for coin in expired:

        del _watchlist[
            coin
        ]


# =========================================================
# GET ACTIVE WATCHLIST
# =========================================================

def get_watchlist() -> List[str]:

    cleanup_expired()

    return sorted(
        _watchlist.keys()
    )


# =========================================================
# GET DETAILS
# =========================================================

def get_watchlist_details() -> List[Dict[str, Any]]:

    cleanup_expired()

    result = []

    timestamp = now()

    for entry in _watchlist.values():

        item = dict(
            entry
        )

        expires_at = item.get(
            "expires_at"
        )

        if expires_at is None:

            item[
                "remaining_seconds"
            ] = None

        else:

            item[
                "remaining_seconds"
            ] = max(
                0,
                round(
                    expires_at
                    - timestamp
                )
            )

        result.append(
            item
        )

    result.sort(
        key=lambda x:
            (
                x.get(
                    "portfolio_held",
                    False
                ),
                x.get(
                    "last_quality_score",
                    0
                ),
            ),
        reverse=True
    )

    return result


# =========================================================
# CHECK IF MONITORED
# =========================================================

def is_monitored(
    coin: str
) -> bool:

    cleanup_expired()

    return (
        normalize_coin(
            coin
        )
        in _watchlist
    )


# =========================================================
# REMOVE MANUALLY
# =========================================================

def remove_coin(
    coin: str
) -> bool:

    coin = normalize_coin(
        coin
    )

    entry = _watchlist.get(
        coin
    )

    if not entry:

        return False

    # Never manually remove a held asset.
    if entry.get(
        "portfolio_held"
    ):

        return False

    del _watchlist[
        coin
    ]

    return True


# =========================================================
# RESET
# =========================================================

def clear_watchlist() -> None:

    # Keep portfolio assets.
    protected = {

        coin: entry

        for coin, entry
        in _watchlist.items()

        if entry.get(
            "portfolio_held"
        )
    }

    _watchlist.clear()

    _watchlist.update(
        protected
    )


# =========================================================
# STATUS
# =========================================================

def get_status() -> Dict[str, Any]:

    cleanup_expired()

    details = get_watchlist_details()

    portfolio_count = sum(
        1
        for item in details
        if item.get(
            "portfolio_held"
        )
    )

    strong_count = sum(
        1
        for item in details
        if item.get(
            "strong_setup"
        )
    )

    return {

        "status":
            "success",

        "version":
            VERSION,

        "watchlist_count":
            len(details),

        "portfolio_count":
            portfolio_count,

        "strong_setup_count":
            strong_count,

        "normal_ttl_hours":
            WATCHLIST_TTL_SECONDS
            / 3600,

        "strong_setup_ttl_hours":
            STRONG_SETUP_TTL_SECONDS
            / 3600,

        "watchlist":
            details,

        "read_only":
            True,
    }
