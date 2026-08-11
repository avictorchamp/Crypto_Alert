"""
Crypto Alert - Watchlist Memory
Version 3.11.0

Purpose:
- Remember dynamic market coins
- Keep normal watchlist entries for 12 hours
- Keep strong setups for 24 hours
- Keep portfolio-held assets permanently while held
- Return sold portfolio assets to normal 12-hour memory
- Store latest analysis snapshot
- Provide watchlist details and status
- READ ONLY
- NO order execution
- NO trading logic

Compatibility:
This module preserves the API expected by:
    app.crypto.price
    app.crypto.watchlist_manager

Required public functions:
    remember_market()
    remember_portfolio()
    get_watchlist()
    get_watchlist_details()
    get_status()
    cleanup_expired()
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


# =========================================================
# VERSION
# =========================================================

VERSION = "3.11.0"


# =========================================================
# MEMORY RULES
# =========================================================

NORMAL_MEMORY_SECONDS = 12 * 60 * 60

STRONG_SETUP_MEMORY_SECONDS = 24 * 60 * 60

PORTFOLIO_MEMORY_SECONDS = None

# Maximum number of remembered non-portfolio coins.
# This protects the service from unlimited memory growth.
MAX_MEMORY_ENTRIES = 500


# =========================================================
# STORAGE
# =========================================================

# Persistent JSON file.
#
# Render may restart the service. Keeping the memory in a
# JSON file allows the watchlist to survive normal restarts
# when the service filesystem is preserved.
#
# The application remains READ ONLY with respect to Binance.
#
# No Binance order/write API is used here.
DEFAULT_STORAGE_FILE = os.path.join(
    os.path.dirname(__file__),
    "watchlist_memory.json",
)

STORAGE_FILE = os.getenv(
    "WATCHLIST_MEMORY_FILE",
    DEFAULT_STORAGE_FILE,
)


# =========================================================
# RUNTIME STATE
# =========================================================

_memory: Dict[str, Dict[str, Any]] = {}

_state_lock = threading.RLock()

_loaded = False

_last_cleanup_at: Optional[float] = None

_last_error: Optional[str] = None

_total_market_updates = 0

_total_portfolio_updates = 0

_total_expired_removed = 0

_total_sold_detected = 0


# =========================================================
# TIME HELPERS
# =========================================================

def now_timestamp() -> float:
    return time.time()


def utc_iso(timestamp: Optional[float] = None) -> Optional[str]:
    if timestamp is None:
        return None

    try:
        return datetime.fromtimestamp(
            float(timestamp),
            tz=timezone.utc,
        ).isoformat()
    except Exception:
        return None


# =========================================================
# SAFE HELPERS
# =========================================================

def safe_float(
    value: Any,
    default: Optional[float] = None,
) -> Optional[float]:
    try:
        if value is None:
            return default

        return float(value)

    except (
        TypeError,
        ValueError,
    ):
        return default


def safe_int(
    value: Any,
    default: Optional[int] = None,
) -> Optional[int]:
    try:
        if value is None:
            return default

        return int(value)

    except (
        TypeError,
        ValueError,
    ):
        return default


def normalize_coin(
    coin: Any,
) -> str:
    """
    Normalize a coin symbol.

    Examples:
        BTC
        btc
        BTCUSDT -> BTC
    """

    if coin is None:
        return ""

    value = str(coin).upper().strip()

    if value.endswith("USDT"):
        value = value[:-4]

    return value.strip()


def normalize_signal(
    value: Any,
) -> str:
    if value is None:
        return "WAIT"

    return str(value).upper().strip()


# =========================================================
# STORAGE LOAD / SAVE
# =========================================================

def _ensure_loaded() -> None:
    global _loaded
    global _last_error

    if _loaded:
        return

    with _state_lock:

        if _loaded:
            return

        try:

            if not os.path.exists(
                STORAGE_FILE
            ):
                _memory.clear()
                _loaded = True
                return

            with open(
                STORAGE_FILE,
                "r",
                encoding="utf-8",
            ) as file:

                data = json.load(file)

            if isinstance(
                data,
                dict,
            ):

                # Support both:
                # {
                #   "memory": {...}
                # }
                #
                # and direct:
                # {
                #   "BTC": {...}
                # }

                if isinstance(
                    data.get("memory"),
                    dict,
                ):
                    loaded_memory = data["memory"]

                else:
                    loaded_memory = data

                _memory.clear()

                for coin, item in loaded_memory.items():

                    if not isinstance(
                        item,
                        dict,
                    ):
                        continue

                    normalized = normalize_coin(
                        coin
                    )

                    if not normalized:
                        continue

                    _memory[
                        normalized
                    ] = dict(item)

            _last_error = None

        except Exception as exc:

            _memory.clear()

            _last_error = (
                f"Storage load error: {exc}"
            )

        finally:

            _loaded = True


def _save() -> None:
    global _last_error

    try:

        directory = os.path.dirname(
            STORAGE_FILE
        )

        if directory:
            os.makedirs(
                directory,
                exist_ok=True,
            )

        payload = {
            "version": VERSION,
            "updated_at": utc_iso(
                now_timestamp()
            ),
            "memory": _memory,
        }

        temporary_file = (
            f"{STORAGE_FILE}.tmp"
        )

        with open(
            temporary_file,
            "w",
            encoding="utf-8",
        ) as file:

            json.dump(
                payload,
                file,
                ensure_ascii=False,
                indent=2,
            )

        os.replace(
            temporary_file,
            STORAGE_FILE,
        )

        _last_error = None

    except Exception as exc:

        _last_error = (
            f"Storage save error: {exc}"
        )


# =========================================================
# ANALYSIS EXTRACTION
# =========================================================

def _extract_entry(
    result: Dict[str, Any],
) -> Dict[str, Any]:

    entry = result.get(
        "entry"
    )

    if isinstance(
        entry,
        dict,
    ):

        return {
            "low": safe_float(
                entry.get("low")
            ),
            "high": safe_float(
                entry.get("high")
            ),
        }

    # Some analyzer versions may return
    # entry_low / entry_high directly.

    return {
        "low": safe_float(
            result.get("entry_low")
        ),
        "high": safe_float(
            result.get("entry_high")
        ),
    }


def _extract_take_profit(
    result: Dict[str, Any],
) -> Dict[str, Any]:

    take_profit = result.get(
        "take_profit"
    )

    if isinstance(
        take_profit,
        dict,
    ):

        return {
            "tp1": safe_float(
                take_profit.get("tp1")
            ),
            "tp2": safe_float(
                take_profit.get("tp2")
            ),
        }

    return {
        "tp1": safe_float(
            result.get("tp1")
        ),
        "tp2": safe_float(
            result.get("tp2")
        ),
    }


def _extract_market_regime(
    result: Dict[str, Any],
) -> Optional[str]:

    regime = result.get(
        "market_regime"
    )

    if isinstance(
        regime,
        dict,
    ):

        value = regime.get(
            "status"
        )

        if value is not None:
            return str(
                value
            ).upper()

    if regime is not None:
        return str(
            regime
        ).upper()

    return None


# =========================================================
# STRONG SETUP
# =========================================================

def detect_strong_setup(
    result: Optional[Dict[str, Any]],
) -> bool:
    """
    Determine whether a setup deserves 24-hour memory.

    Strong setup requires several positive characteristics.
    This deliberately does NOT generate a trading signal.

    Strong setup criteria:
    - quality >= 80
    - risk/reward >= 1.5
    - BUY/STRONG BUY signal
    - bullish market regime
    - actionable entry status when available
    """

    if not isinstance(
        result,
        dict,
    ):
        return False

    quality = safe_float(
        result.get(
            "quality_score"
        )
    )

    risk_reward = safe_float(
        result.get(
            "risk_reward"
        )
    )

    signal = normalize_signal(
        result.get(
            "signal"
        )
    )

    regime = _extract_market_regime(
        result
    )

    trade_status = str(
        result.get(
            "trade_status",
            ""
        )
    ).upper()

    trade_action = str(
        result.get(
            "trade_action",
            ""
        )
    ).upper()

    # Strong setup requires quality.
    if (
        quality is None
        or quality < 80
    ):
        return False

    # Strong setup should have meaningful R/R.
    if (
        risk_reward is None
        or risk_reward < 1.5
    ):
        return False

    # Only BUY-side setups receive the
    # longer strong-setup memory.
    if signal not in {
        "BUY SETUP",
        "STRONG BUY",
        "BUY",
    }:
        return False

    # BUY setup should be aligned with market regime.
    if regime != "BULLISH":
        return False

    # If trade status is available, it should be actionable.
    if trade_status:

        if trade_status not in {
            "IN_ENTRY",
            "READY",
        }:

            # WAIT_FOR_ENTRY is not considered strong
            # enough for the 24-hour memory.
            return False

    if trade_action:

        if trade_action not in {
            "READY",
            "BUY",
            "ENTER",
        }:

            return False

    return True


# =========================================================
# SNAPSHOT
# =========================================================

def _build_snapshot(
    coin: str,
    result: Dict[str, Any],
) -> Dict[str, Any]:

    entry = _extract_entry(
        result
    )

    take_profit = _extract_take_profit(
        result
    )

    regime = _extract_market_regime(
        result
    )

    return {

        "coin":
            coin,

        "last_price":
            safe_float(
                result.get(
                    "price"
                )
            ),

        "signal":
            normalize_signal(
                result.get(
                    "signal"
                )
            ),

        "confidence":
            safe_float(
                result.get(
                    "confidence"
                )
            ),

        "quality_score":
            safe_float(
                result.get(
                    "quality_score"
                )
            ),

        "quality_grade":
            result.get(
                "quality_grade"
            ),

        "rsi":
            safe_float(
                result.get(
                    "rsi"
                )
            ),

        "ema20":
            safe_float(
                result.get(
                    "ema20"
                )
            ),

        "ema50":
            safe_float(
                result.get(
                    "ema50"
                )
            ),

        "support":
            safe_float(
                result.get(
                    "support"
                )
            ),

        "resistance":
            safe_float(
                result.get(
                    "resistance"
                )
            ),

        "entry":
            entry,

        "stop_loss":
            safe_float(
                result.get(
                    "stop_loss"
                )
            ),

        "take_profit":
            take_profit,

        "risk_reward":
            safe_float(
                result.get(
                    "risk_reward"
                )
            ),

        "trade_status":
            result.get(
                "trade_status"
            ),

        "trade_action":
            result.get(
                "trade_action"
            ),

        "market_regime":
            regime,

        "reason":
            result.get(
                "reason",
                [],
            ),

    }


# =========================================================
# EXPIRATION
# =========================================================

def _get_expiration_seconds(
    item: Dict[str, Any],
) -> Optional[int]:

    if item.get(
        "portfolio_held"
    ):
        return None

    if item.get(
        "strong_setup"
    ):
        return STRONG_SETUP_MEMORY_SECONDS

    return NORMAL_MEMORY_SECONDS


def _is_expired(
    item: Dict[str, Any],
    current_time: Optional[float] = None,
) -> bool:

    if current_time is None:
        current_time = now_timestamp()

    if item.get(
        "portfolio_held"
    ):
        return False

    last_seen = safe_float(
        item.get(
            "last_seen"
        )
    )

    if last_seen is None:
        return True

    duration = _get_expiration_seconds(
        item
    )

    if duration is None:
        return False

    return (
        current_time - last_seen
        >= duration
    )


def _remaining_seconds(
    item: Dict[str, Any],
    current_time: Optional[float] = None,
) -> Optional[int]:

    if item.get(
        "portfolio_held"
    ):
        return None

    if current_time is None:
        current_time = now_timestamp()

    last_seen = safe_float(
        item.get(
            "last_seen"
        )
    )

    if last_seen is None:
        return 0

    duration = _get_expiration_seconds(
        item
    )

    if duration is None:
        return None

    remaining = (
        duration
        - (
            current_time
            - last_seen
        )
    )

    return max(
        0,
        int(
            remaining
        )
    )


# =========================================================
# MEMORY ENTRY
# =========================================================

def _create_or_get_entry(
    coin: str,
) -> Dict[str, Any]:

    existing = _memory.get(
        coin
    )

    if existing is None:

        existing = {

            "coin":
                coin,

            "first_seen":
                now_timestamp(),

            "last_seen":
                now_timestamp(),

            "last_market_seen":
                now_timestamp(),

            "last_portfolio_seen":
                None,

            "portfolio_held":
                False,

            "portfolio_quantity":
                0.0,

            "portfolio_current_price":
                None,

            "portfolio_value_usdt":
                None,

            "strong_setup":
                False,

            "memory_type":
                "NORMAL",

            "source":
                "DYNAMIC_MARKET",

            "previously_held":
                False,

            "sold_at":
                None,

            "sold_from_portfolio":
                False,

            "snapshot":
                {},

            "last_updated":
                now_timestamp(),

        }

        _memory[
            coin
        ] = existing

    return existing


# =========================================================
# REMEMBER MARKET
# =========================================================

def remember_market(
    market: Any,
) -> Dict[str, Any]:
    """
    Remember current dynamic market data.

    Accepted input:

    List:
        [
            {
                "coin": "BTC",
                "price": ...,
                ...
            }
        ]

    Dict:
        {
            "BTC": {...},
            "ETH": {...}
        }

    Or:
        {
            "data": [...]
        }
    """

    global _total_market_updates

    _ensure_loaded()

    current_time = now_timestamp()

    # Normalize input.
    if isinstance(
        market,
        dict,
    ):

        if isinstance(
            market.get("data"),
            list,
        ):

            market_items = market.get(
                "data"
            )

        else:

            market_items = []

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

                    market_items.append(
                        item
                    )

    elif isinstance(
        market,
        list,
    ):

        market_items = market

    else:

        market_items = []

    remembered = []

    with _state_lock:

        for item in market_items:

            if not isinstance(
                item,
                dict,
            ):
                continue

            coin = normalize_coin(
                item.get(
                    "coin"
                )
            )

            if not coin:

                coin = normalize_coin(
                    item.get(
                        "symbol"
                    )
                )

            if not coin:
                continue

            entry = _create_or_get_entry(
                coin
            )

            was_held = bool(
                entry.get(
                    "portfolio_held"
                )
            )

            entry[
                "last_market_seen"
            ] = current_time

            entry[
                "last_seen"
            ] = current_time

            entry[
                "last_updated"
            ] = current_time

            entry[
                "source"
            ] = (
                "PORTFOLIO_AND_DYNAMIC"
                if was_held
                else "DYNAMIC_MARKET"
            )

            snapshot = _build_snapshot(
                coin,
                item,
            )

            entry[
                "snapshot"
            ] = snapshot

            strong = detect_strong_setup(
                item
            )

            entry[
                "strong_setup"
            ] = strong

            if was_held:

                entry[
                    "memory_type"
                ] = "PORTFOLIO_HELD"

            elif strong:

                entry[
                    "memory_type"
                ] = "STRONG_SETUP"

            else:

                entry[
                    "memory_type"
                ] = "NORMAL"

            # If a sold coin comes back into
            # dynamic market monitoring, it is
            # considered active again.
            if entry.get(
                "sold_from_portfolio"
            ):

                entry[
                    "sold_from_portfolio"
                ] = False

                entry[
                    "sold_at"
                ] = None

            remembered.append(
                coin
            )

        _total_market_updates += 1

        _enforce_memory_limit_locked()

        _save()

    return {
        "status": "success",
        "remembered_count": len(
            remembered
        ),
        "coins": sorted(
            set(remembered)
        ),
        "read_only": True,
    }


# =========================================================
# PORTFOLIO NORMALIZATION
# =========================================================

def _normalize_portfolio(
    portfolio: Any,
) -> List[Dict[str, Any]]:

    if portfolio is None:
        return []

    if isinstance(
        portfolio,
        list,
    ):
        return [
            item
            for item in portfolio
            if isinstance(
                item,
                dict,
            )
        ]

    if not isinstance(
        portfolio,
        dict,
    ):
        return []

    positions = portfolio.get(
        "positions"
    )

    if isinstance(
        positions,
        list,
    ):

        return [
            item
            for item in positions
            if isinstance(
                item,
                dict,
            )
        ]

    nested = portfolio.get(
        "portfolio"
    )

    if isinstance(
        nested,
        dict,
    ):

        positions = nested.get(
            "positions"
        )

        if isinstance(
            positions,
            list,
        ):

            return [
                item
                for item in positions
                if isinstance(
                    item,
                    dict,
                )
            ]

        assets = nested.get(
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

                total = safe_float(
                    asset.get(
                        "total"
                    ),
                    0.0,
                )

                if total is None:
                    total = 0.0

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

                        "value_usdt":
                            asset.get(
                                "value_usdt"
                            ),
                    }
                )

            return result

    return []


# =========================================================
# REMEMBER PORTFOLIO
# =========================================================

def remember_portfolio(
    portfolio: Any,
) -> Dict[str, Any]:
    """
    Remember assets currently held.

    Portfolio is expected to come from Binance TH
    READ_ONLY API.

    This function never submits orders.
    """

    global _total_portfolio_updates
    global _total_sold_detected

    _ensure_loaded()

    current_time = now_timestamp()

    positions = _normalize_portfolio(
        portfolio
    )

    current_assets = set()

    remembered = []

    with _state_lock:

        # -------------------------------------------------
        # Current holdings
        # -------------------------------------------------

        for position in positions:

            if not isinstance(
                position,
                dict,
            ):
                continue

            coin = normalize_coin(
                position.get(
                    "asset"
                )
            )

            if not coin:
                continue

            quantity = safe_float(
                position.get(
                    "quantity",
                    position.get(
                        "total",
                        0,
                    ),
                ),
                0.0,
            )

            if quantity is None:
                quantity = 0.0

            if quantity <= 0:
                continue

            current_assets.add(
                coin
            )

            entry = _create_or_get_entry(
                coin
            )

            entry[
                "portfolio_held"
            ] = True

            entry[
                "previously_held"
            ] = True

            entry[
                "portfolio_quantity"
            ] = quantity

            entry[
                "portfolio_current_price"
            ] = safe_float(
                position.get(
                    "current_price",
                    position.get(
                        "price_usdt"
                    ),
                )
            )

            entry[
                "portfolio_value_usdt"
            ] = safe_float(
                position.get(
                    "value_usdt"
                )
            )

            entry[
                "last_portfolio_seen"
            ] = current_time

            entry[
                "last_seen"
            ] = current_time

            entry[
                "last_updated"
            ] = current_time

            entry[
                "memory_type"
            ] = "PORTFOLIO_HELD"

            entry[
                "source"
            ] = "PORTFOLIO"

            entry[
                "sold_from_portfolio"
            ] = False

            entry[
                "sold_at"
            ] = None

            remembered.append(
                coin
            )

        # -------------------------------------------------
        # Detect previously-held coins that disappeared.
        #
        # Binance is the source of truth.
        # A coin that was held previously but is no longer
        # present becomes a normal 12-hour watchlist entry.
        # -------------------------------------------------

        for coin, entry in _memory.items():

            if not entry.get(
                "portfolio_held"
            ):
                continue

            if coin in current_assets:
                continue

            # The portfolio snapshot no longer contains
            # this asset.
            entry[
                "portfolio_held"
            ] = False

            entry[
                "portfolio_quantity"
            ] = 0.0

            entry[
                "portfolio_current_price"
            ] = None

            entry[
                "portfolio_value_usdt"
            ] = None

            entry[
                "sold_at"
            ] = current_time

            entry[
                "sold_from_portfolio"
            ] = True

            entry[
                "last_seen"
            ] = current_time

            entry[
                "last_updated"
            ] = current_time

            # Sold coins receive normal 12-hour memory.
            entry[
                "strong_setup"
            ] = False

            entry[
                "memory_type"
            ] = "SOLD_PORTFOLIO"

            entry[
                "source"
            ] = "SOLD_PORTFOLIO"

            _total_sold_detected += 1

        _total_portfolio_updates += 1

        _enforce_memory_limit_locked()

        _save()

    return {
        "status": "success",
        "current_portfolio_count": len(
            current_assets
        ),
        "coins": sorted(
            current_assets
        ),
        "sold_detected": _total_sold_detected,
        "read_only": True,
    }


# =========================================================
# CLEANUP
# =========================================================

def cleanup_expired() -> Dict[str, Any]:
    """
    Remove normal/strong entries that exceeded their memory.
    Portfolio-held entries never expire.
    """

    global _last_cleanup_at
    global _total_expired_removed

    _ensure_loaded()

    current_time = now_timestamp()

    removed = []

    with _state_lock:

        for coin in list(
            _memory.keys()
        ):

            item = _memory.get(
                coin
            )

            if not isinstance(
                item,
                dict,
            ):
                del _memory[
                    coin
                ]

                removed.append(
                    coin
                )

                continue

            if _is_expired(
                item,
                current_time,
            ):

                del _memory[
                    coin
                ]

                removed.append(
                    coin
                )

        _last_cleanup_at = current_time

        _total_expired_removed += len(
            removed
        )

        if removed:
            _save()

    return {
        "status": "success",
        "removed_count": len(
            removed
        ),
        "removed": sorted(
            removed
        ),
        "remaining_count": len(
            _memory
        ),
    }


# =========================================================
# INTERNAL MEMORY LIMIT
# =========================================================

def _enforce_memory_limit_locked() -> None:
    """
    Protect memory from unlimited growth.

    Portfolio-held entries are always protected.

    Non-held entries with the oldest last_seen time
    are removed first.
    """

    if len(
        _memory
    ) <= MAX_MEMORY_ENTRIES:
        return

    candidates = []

    for coin, item in _memory.items():

        if item.get(
            "portfolio_held"
        ):
            continue

        last_seen = safe_float(
            item.get(
                "last_seen"
            ),
            0.0,
        )

        if last_seen is None:
            last_seen = 0.0

        candidates.append(
            (
                last_seen,
                coin,
            )
        )

    candidates.sort(
        key=lambda x: x[0]
    )

    remove_count = (
        len(_memory)
        - MAX_MEMORY_ENTRIES
    )

    for _, coin in candidates[
        :remove_count
    ]:

        _memory.pop(
            coin,
            None,
        )


# =========================================================
# GET WATCHLIST
# =========================================================

def get_watchlist() -> List[str]:
    """
    Return active monitored coin names.

    Used directly by app.crypto.price.

    Expired entries are removed automatically.
    """

    _ensure_loaded()

    cleanup_expired()

    with _state_lock:

        return sorted(
            set(
                coin
                for coin, item
                in _memory.items()
                if isinstance(
                    item,
                    dict,
                )
                and not _is_expired(
                    item
                )
            )
        )


# =========================================================
# GET WATCHLIST DETAILS
# =========================================================

def get_watchlist_details() -> List[Dict[str, Any]]:
    """
    Return detailed watchlist state.
    """

    _ensure_loaded()

    cleanup_expired()

    current_time = now_timestamp()

    result = []

    with _state_lock:

        for coin, item in _memory.items():

            if not isinstance(
                item,
                dict,
            ):
                continue

            if _is_expired(
                item,
                current_time,
            ):
                continue

            duration = _get_expiration_seconds(
                item
            )

            remaining = _remaining_seconds(
                item,
                current_time,
            )

            snapshot = item.get(
                "snapshot",
                {},
            )

            if not isinstance(
                snapshot,
                dict,
            ):
                snapshot = {}

            details = {

                "coin":
                    coin,

                "memory_type":
                    item.get(
                        "memory_type",
                        "NORMAL",
                    ),

                "portfolio_held":
                    bool(
                        item.get(
                            "portfolio_held"
                        )
                    ),

                "previously_held":
                    bool(
                        item.get(
                            "previously_held"
                        )
                    ),

                "sold_from_portfolio":
                    bool(
                        item.get(
                            "sold_from_portfolio"
                        )
                    ),

                "strong_setup":
                    bool(
                        item.get(
                            "strong_setup"
                        )
                    ),

                "source":
                    item.get(
                        "source"
                    ),

                "first_seen":
                    utc_iso(
                        safe_float(
                            item.get(
                                "first_seen"
                            )
                        )
                    ),

                "last_seen":
                    utc_iso(
                        safe_float(
                            item.get(
                                "last_seen"
                            )
                        )
                    ),

                "last_market_seen":
                    utc_iso(
                        safe_float(
                            item.get(
                                "last_market_seen"
                            )
                        )
                    ),

                "last_portfolio_seen":
                    utc_iso(
                        safe_float(
                            item.get(
                                "last_portfolio_seen"
                            )
                        )
                    ),

                "sold_at":
                    utc_iso(
                        safe_float(
                            item.get(
                                "sold_at"
                            )
                        )
                    ),

                "expires_at":
                    (
                        None
                        if duration is None
                        else utc_iso(
                            safe_float(
                                item.get(
                                    "last_seen"
                                ),
                                current_time,
                            )
                            + duration
                        )
                    ),

                "remaining_seconds":
                    remaining,

                "remaining_hours":
                    (
                        None
                        if remaining is None
                        else round(
                            remaining / 3600,
                            2,
                        )
                    ),

                "portfolio":
                    {
                        "quantity":
                            item.get(
                                "portfolio_quantity",
                                0.0,
                            ),

                        "current_price":
                            item.get(
                                "portfolio_current_price"
                            ),

                        "value_usdt":
                            item.get(
                                "portfolio_value_usdt"
                            ),
                    },

                "snapshot":
                    snapshot,

            }

            # Expose the latest important analysis fields
            # at top level too. This makes /watchlist easier
            # to read without breaking the complete snapshot.

            details.update({

                "last_price":
                    snapshot.get(
                        "last_price"
                    ),

                "signal":
                    snapshot.get(
                        "signal"
                    ),

                "confidence":
                    snapshot.get(
                        "confidence"
                    ),

                "quality_score":
                    snapshot.get(
                        "quality_score"
                    ),

                "quality_grade":
                    snapshot.get(
                        "quality_grade"
                    ),

                "rsi":
                    snapshot.get(
                        "rsi"
                    ),

                "ema20":
                    snapshot.get(
                        "ema20"
                    ),

                "ema50":
                    snapshot.get(
                        "ema50"
                    ),

                "support":
                    snapshot.get(
                        "support"
                    ),

                "resistance":
                    snapshot.get(
                        "resistance"
                    ),

                "entry":
                    snapshot.get(
                        "entry"
                    ),

                "stop_loss":
                    snapshot.get(
                        "stop_loss"
                    ),

                "take_profit":
                    snapshot.get(
                        "take_profit"
                    ),

                "risk_reward":
                    snapshot.get(
                        "risk_reward"
                    ),

                "trade_status":
                    snapshot.get(
                        "trade_status"
                    ),

                "trade_action":
                    snapshot.get(
                        "trade_action"
                    ),

                "market_regime":
                    snapshot.get(
                        "market_regime"
                    ),

                "reason":
                    snapshot.get(
                        "reason",
                        [],
                    ),

            })

            result.append(
                details
            )

    result.sort(
        key=lambda item: (
            not item.get(
                "portfolio_held",
                False,
            ),
            not item.get(
                "strong_setup",
                False,
            ),
            item.get(
                "coin",
                "",
            ),
        )
    )

    return result


# =========================================================
# GET STATUS
# =========================================================

def get_status() -> Dict[str, Any]:
    """
    Return watchlist memory status.
    """

    _ensure_loaded()

    cleanup_expired()

    details = get_watchlist_details()

    portfolio_count = 0

    strong_count = 0

    normal_count = 0

    sold_count = 0

    for item in details:

        if item.get(
            "portfolio_held"
        ):

            portfolio_count += 1

        elif item.get(
            "strong_setup"
        ):

            strong_count += 1

        else:

            normal_count += 1

        if item.get(
            "sold_from_portfolio"
        ):

            sold_count += 1

    return {

        "status":
            "success",

        "version":
            VERSION,

        "total":
            len(details),

        "normal_count":
            normal_count,

        "strong_setup_count":
            strong_count,

        "portfolio_held_count":
            portfolio_count,

        "sold_portfolio_count":
            sold_count,

        "memory_rules":
            {
                "normal_hours":
                    NORMAL_MEMORY_SECONDS / 3600,

                "strong_setup_hours":
                    STRONG_SETUP_MEMORY_SECONDS / 3600,

                "portfolio_held":
                    "PERMANENT_WHILE_HELD",

                "sold_portfolio_hours":
                    NORMAL_MEMORY_SECONDS / 3600,
            },

        "storage":
            {
                "file":
                    STORAGE_FILE,

                "loaded":
                    _loaded,

                "persistent":
                    True,
            },

        "statistics":
            {
                "market_updates":
                    _total_market_updates,

                "portfolio_updates":
                    _total_portfolio_updates,

                "expired_removed":
                    _total_expired_removed,

                "sold_detected":
                    _total_sold_detected,
            },

        "last_cleanup_at":
            utc_iso(
                _last_cleanup_at
            ),

        "last_error":
            _last_error,

        "read_only":
            True,

        "automatic_trading":
            False,
    }


# =========================================================
# ALIASES / COMPATIBILITY HELPERS
# =========================================================

def get_watchlist_summary() -> Dict[str, Any]:
    """
    Compatibility helper for callers that want a compact
    summary directly from this module.
    """

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
            sorted(
                set(portfolio)
            ),

        "strong_setup":
            sorted(
                set(strong)
            ),

        "normal":
            sorted(
                set(normal)
            ),

        "read_only":
            True,

    }


def is_coin_monitored(
    coin: str,
) -> bool:

    target = normalize_coin(
        coin
    )

    return target in set(
        get_watchlist()
    )


def get_portfolio_coins() -> List[str]:

    return sorted(
        set(
            item.get(
                "coin"
            )
            for item in get_watchlist_details()
            if item.get(
                "portfolio_held"
            )
            and item.get(
                "coin"
            )
        )
    )


def get_strong_setup_coins() -> List[str]:

    return sorted(
        set(
            item.get(
                "coin"
            )
            for item in get_watchlist_details()
            if item.get(
                "strong_setup"
            )
            and item.get(
                "coin"
            )
        )
    )


# =========================================================
# READ-ONLY CHECK
# =========================================================

def is_read_only() -> bool:
    return True


# =========================================================
# INITIALIZE
# =========================================================

_ensure_loaded()
