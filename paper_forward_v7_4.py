#!/usr/bin/env python3
"""
V7.4 BNB Paper Forward Recorder
Research only. NEVER executes real trades.

Strategy LOCKED:
- Symbol: BNBUSDT
- Higher timeframe: 1D
- Lower timeframe: 1H
- Regime: 1D_BULL_FILTER
- Entry rule: momentum
- Horizon: 24 hours

Paper Forward is cumulative.
It never performs retrospective backfill before the forward-test start.
"""

from __future__ import annotations

import io
import json
import os
import zipfile

from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError
from urllib.request import Request, urlopen


# ============================================================
# LOCKED STRATEGY CONFIG
# ============================================================

SYMBOL = "BNBUSDT"
HORIZON_HOURS = 24

FEE = 0.001
SLIPPAGE = 0.0005

# IMPORTANT:
# This is the independent paper-forward starting point.
# DO NOT change this to improve results.
FORWARD_TEST_START_UTC = "2026-08-28T23:00:00+00:00"

LOG_FILE = "paper_forward_v7_4_log.json"


# ============================================================
# BINANCE VISION DATA
# ============================================================

MONTHLY_1H = (
    "https://data.binance.vision/data/spot/monthly/klines/"
    "{symbol}/1h/{symbol}-1h-{month}.zip"
)

MONTHLY_1D = (
    "https://data.binance.vision/data/spot/monthly/klines/"
    "{symbol}/1d/{symbol}-1d-{month}.zip"
)

DAILY_1H = (
    "https://data.binance.vision/data/spot/daily/klines/"
    "{symbol}/1h/{date}.zip"
)

DAILY_1D = (
    "https://data.binance.vision/data/spot/daily/klines/"
    "{symbol}/1d/{date}.zip"
)


# ============================================================
# HELPERS
# ============================================================

def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def months(start: datetime, end: datetime):
    y = start.year
    m = start.month

    while (y, m) <= (end.year, end.month):
        yield f"{y:04d}-{m:02d}"

        m += 1
        if m == 13:
            y += 1
            m = 1


def days(start: datetime, end: datetime):
    current = start

    while current.date() <= end.date():
        yield current.strftime("%Y-%m-%d")
        current += timedelta(days=1)


def get(url: str):
    try:
        request = Request(
            url,
            headers={
                "User-Agent": "CryptoAlert-PaperForward/7.4"
            },
        )

        with urlopen(request, timeout=30) as response:
            return response.read()

    except HTTPError as exc:
        if exc.code == 404:
            return None
        raise


# ============================================================
# CSV READER
# ============================================================

def read_zip_data(data, start, end, output):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:

        csv_files = [
            name
            for name in archive.namelist()
            if name.lower().endswith(".csv")
        ]

        if not csv_files:
            return

        with archive.open(csv_files[0]) as file:

            for raw in file:

                fields = raw.decode().strip().split(",")

                if len(fields) < 6:
                    continue

                if not fields[0].isdigit():
                    continue

                timestamp = int(fields[0])

                # Normalize microseconds/nanoseconds if encountered.
                while timestamp > 10_000_000_000_000:
                    timestamp //= 1000

                dt = datetime.fromtimestamp(
                    timestamp / 1000,
                    timezone.utc,
                )

                if start <= dt <= end:

                    output.append(
                        {
                            "t": timestamp,
                            "o": float(fields[1]),
                            "h": float(fields[2]),
                            "l": float(fields[3]),
                            "c": float(fields[4]),
                            "v": float(fields[5]),
                        }
                    )


# ============================================================
# DATA FETCH
# ============================================================

def fetch(kind: str, start: datetime, end: datetime):

    output = []

    if kind == "1h":
        monthly_url = MONTHLY_1H
        daily_url = DAILY_1H
    else:
        monthly_url = MONTHLY_1D
        daily_url = DAILY_1D

    for month in months(start, end):

        data = get(
            monthly_url.format(
                symbol=SYMBOL,
                month=month,
            )
        )

        if data is not None:
            read_zip_data(
                data,
                start,
                end,
                output,
            )
            continue

        month_start = datetime.strptime(
            month + "-01",
            "%Y-%m-%d",
        ).replace(tzinfo=timezone.utc)

        month_end = (
            month_start
            + timedelta(days=32)
        ).replace(day=1) - timedelta(seconds=1)

        range_start = max(start, month_start)
        range_end = min(end, month_end)

        for date in days(range_start, range_end):

            data = get(
                daily_url.format(
                    symbol=SYMBOL,
                    date=date,
                )
            )

            if data is not None:
                read_zip_data(
                    data,
                    start,
                    end,
                    output,
                )

    output.sort(key=lambda x: x["t"])

    return output


# ============================================================
# INDICATORS
# ============================================================

def ema(values, period):

    multiplier = 2 / (period + 1)

    value = values[0]

    for current in values[1:]:
        value = (
            current * multiplier
            + value * (1 - multiplier)
        )

    return value


def rsi(values, period=14):

    gains = sum(
        max(b - a, 0)
        for a, b in zip(
            values[-period - 1:-1],
            values[-period:],
        )
    )

    losses = sum(
        max(a - b, 0)
        for a, b in zip(
            values[-period - 1:-1],
            values[-period:],
        )
    )

    if gains + losses == 0:
        return 50

    if losses == 0:
        return 100

    return 100 - 100 / (1 + gains / losses)


# ============================================================
# 1D REGIME FILTER
# ============================================================

def regime(daily):

    closes = [
        candle["c"]
        for candle in daily[-50:]
    ]

    ema20 = ema(
        closes[-20:],
        20,
    )

    ema50 = ema(
        closes,
        50,
    )

    if ema20 > ema50 * 1.002:
        return "BULL"

    if ema20 < ema50 * 0.998:
        return "BEAR"

    return "SIDEWAYS"


# ============================================================
# LOCKED MOMENTUM ENTRY RULE
# ============================================================

def signal(hourly, daily):

    closes = [
        candle["c"]
        for candle in hourly[-51:]
    ]

    price = closes[-1]

    average20 = sum(
        closes[-20:]
    ) / 20

    ema20 = ema(
        closes[-20:],
        20,
    )

    ema50 = ema(
        closes[-50:],
        50,
    )

    current_rsi = rsi(closes)

    current_volume = hourly[-1]["v"]

    average_volume = (
        sum(
            candle["v"]
            for candle in hourly[-21:-1]
        )
        / 20
    )

    support = min(
        closes[-20:]
    )

    resistance = max(
        closes[-20:]
    )

    denominator = (
        price - support * 0.99
    )

    if support > 0 and denominator > 0:
        risk_reward = (
            resistance - price
        ) / denominator
    else:
        risk_reward = 0

    current_regime = regime(daily)

    momentum_signal = (
        current_regime == "BULL"
        and ema20 > ema50
        and price > average20 * 1.01
        and current_volume >= 1.5 * average_volume
        and risk_reward >= 1
    )

    return {
        "signal": momentum_signal,
        "price": price,
        "regime": current_regime,
        "rsi": current_rsi,
        "volume_ratio": (
            current_volume / average_volume
            if average_volume
            else None
        ),
        "risk_reward": risk_reward,
        "ema20": ema20,
        "ema50": ema50,
    }


# ============================================================
# CLOSE PAPER TRADES
# ============================================================

def close_ready(observations, hourly):

    horizon_ms = (
        HORIZON_HOURS
        * 60
        * 60
        * 1000
    )

    for observation in observations:

        if observation.get("status") != "OPEN":
            continue

        if not observation.get("signal"):
            continue

        entry_timestamp = int(
            observation[
                "signal_candle_close_ms"
            ]
        )

        target_timestamp = (
            entry_timestamp
            + horizon_ms
        )

        future = [
            candle
            for candle in hourly
            if candle["t"] >= target_timestamp
        ]

        if not future:
            continue

        exit_candle = future[0]

        entry_price = float(
            observation["price"]
        )

        exit_price = float(
            exit_candle["c"]
        )

        gross_return = (
            exit_price
            / entry_price
            - 1
        ) * 100

        net_return = (
            gross_return
            - (FEE + SLIPPAGE) * 100
        )

        observation[
            "exit_time_utc"
        ] = datetime.fromtimestamp(
            exit_candle["t"] / 1000,
            timezone.utc,
        ).isoformat()

        observation[
            "exit_price"
        ] = exit_price

        observation[
            "paper_return_pct"
        ] = round(
            net_return,
            4,
        )

        observation["status"] = "CLOSED"


# ============================================================
# PERFORMANCE SUMMARY
# ============================================================

def summary(observations):

    closed_returns = [
        float(
            observation["paper_return_pct"]
        )
        for observation in observations
        if observation.get("status") == "CLOSED"
    ]

    winning_returns = [
        value
        for value in closed_returns
        if value > 0
    ]

    losing_returns = [
        value
        for value in closed_returns
        if value < 0
    ]

    number_closed = len(
        closed_returns
    )

    number_winners = len(
        winning_returns
    )

    number_losers = len(
        losing_returns
    )

    win_rate = (
        100 * number_winners / number_closed
        if number_closed
        else None
    )

    average_return = (
        sum(closed_returns)
        / number_closed
        if number_closed
        else None
    )

    expectancy = average_return

    gross_profit = sum(
        winning_returns
    )

    gross_loss = -sum(
        losing_returns
    )

    profit_factor = (
        gross_profit / gross_loss
        if gross_loss > 0
        else None
    )

    # Equity curve
    equity = 1.0
    peak = 1.0
    max_drawdown = 0.0

    for return_pct in closed_returns:

        equity *= (
            1 + return_pct / 100
        )

        peak = max(
            peak,
            equity,
        )

        drawdown = (
            peak - equity
        ) / peak * 100

        max_drawdown = max(
            max_drawdown,
            drawdown,
        )

    open_trades = sum(
        1
        for observation in observations
        if observation.get("status") == "OPEN"
    )

    return {
        "closed_trades": number_closed,
        "winning_trades": number_winners,
        "losing_trades": number_losers,
        "win_rate_pct": (
            round(win_rate, 2)
            if win_rate is not None
            else None
        ),
        "average_return_pct": (
            round(average_return, 4)
            if average_return is not None
            else None
        ),
        "expectancy_pct": (
            round(expectancy, 4)
            if expectancy is not None
            else None
        ),
        "profit_factor": (
            round(profit_factor, 3)
            if profit_factor is not None
            else None
        ),
        "max_drawdown_pct": round(
            max_drawdown,
            4,
        ),
        "open_trades": open_trades,
    }


# ============================================================
# MAIN
# ============================================================

def main():

    now = datetime.now(
        timezone.utc
    )

    forward_start = parse_iso(
        FORWARD_TEST_START_UTC
    )

    # Fetch enough history for indicators
    # but only record observations from
    # the independent forward-test start.
    data_start = min(
        forward_start - timedelta(days=90),
        now - timedelta(days=90),
    )

    hourly = fetch(
        "1h",
        data_start,
        now,
    )

    daily = fetch(
        "1d",
        data_start,
        now,
    )

    if len(hourly) < 51:
        raise RuntimeError(
            f"insufficient 1H data: {len(hourly)}"
        )

    if len(daily) < 50:
        raise RuntimeError(
            f"insufficient 1D data: {len(daily)}"
        )

    # --------------------------------------------------------
    # Default cumulative structure
    # --------------------------------------------------------

    data = {
        "version": "7.4.0",
        "purpose": "BNB_PAPER_FORWARD",
        "symbol": SYMBOL,
        "rule": "momentum",
        "context": "1D_BULL_FILTER",
        "horizon_hours": HORIZON_HOURS,
        "forward_test_start_utc": FORWARD_TEST_START_UTC,
        "observations": [],
        "production_changed": False,
    }

    # --------------------------------------------------------
    # Load existing cumulative log
    # --------------------------------------------------------

    if os.path.exists(LOG_FILE):

        with open(
            LOG_FILE,
            "r",
            encoding="utf-8",
        ) as file:

            existing = json.load(file)

        # Safety checks.
        if existing.get("symbol") != SYMBOL:
            raise RuntimeError(
                "existing paper log symbol mismatch"
            )

        if existing.get("rule") != "momentum":
            raise RuntimeError(
                "existing paper log strategy mismatch"
            )

        if existing.get("context") != "1D_BULL_FILTER":
            raise RuntimeError(
                "existing paper log context mismatch"
            )

        if existing.get("production_changed") is not False:
            raise RuntimeError(
                "production guard mismatch"
            )

        existing_start = existing.get(
            "forward_test_start_utc"
        )

        if existing_start != FORWARD_TEST_START_UTC:
            raise RuntimeError(
                "forward-test start mismatch"
            )

        data = existing

    # --------------------------------------------------------
    # Close previously opened paper trades
    # --------------------------------------------------------

    close_ready(
        data["observations"],
        hourly,
    )

    # --------------------------------------------------------
    # Existing observation timestamps
    # --------------------------------------------------------

    seen = {
        int(
            observation[
                "signal_candle_close_ms"
            ]
        )
        for observation in data["observations"]
        if observation.get(
            "signal_candle_close_ms"
        ) is not None
    }

    # --------------------------------------------------------
    # Find canonical 23:00 UTC daily observations
    # --------------------------------------------------------

    candidates = []

    for candle in hourly:

        candle_time = datetime.fromtimestamp(
            candle["t"] / 1000,
            timezone.utc,
        )

        if candle_time.hour != 23:
            continue

        if candle["t"] in seen:
            continue

        # CRITICAL:
        # Never create an observation before
        # the independent forward-test start.
        if candle_time < forward_start:
            continue

        # Do not use a candle that is in the future.
        if candle_time > now:
            continue

        candidates.append(candle)

    # --------------------------------------------------------
    # New test:
    # record ONLY latest completed observation.
    #
    # Existing test:
    # catch up missed observations,
    # but never go before forward_start.
    # --------------------------------------------------------

    if not seen:
        candidates = candidates[-1:]
    else:
        candidates = candidates[-90:]

    # --------------------------------------------------------
    # Generate observations
    # --------------------------------------------------------

    for last_candle in candidates:

        observation_time = datetime.fromtimestamp(
            last_candle["t"] / 1000,
            timezone.utc,
        )

        day_start = observation_time.replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )

        # Only COMPLETED 1D candles.
        completed_daily = [
            candle
            for candle in daily
            if candle["t"]
            < int(
                day_start.timestamp()
                * 1000
            )
        ]

        if len(completed_daily) < 50:
            continue

        history = [
            candle
            for candle in hourly
            if candle["t"]
            <= last_candle["t"]
        ]

        if len(history) < 51:
            continue

        result = signal(
            history,
            completed_daily,
        )

        data["observations"].append(
            {
                "signal_time_utc":
                    observation_time.isoformat(),

                "signal_candle_close_ms":
                    last_candle["t"],

                "signal":
                    bool(result["signal"]),

                "price":
                    result["price"],

                "regime":
                    result["regime"],

                "rsi":
                    result["rsi"],

                "volume_ratio":
                    result["volume_ratio"],

                "risk_reward":
                    result["risk_reward"],

                "ema20":
                    result["ema20"],

                "ema50":
                    result["ema50"],

                "status":
                    "OPEN"
                    if result["signal"]
                    else "NO_TRADE",
            }
        )

    # --------------------------------------------------------
    # Sort + summary
    # --------------------------------------------------------

    data["observations"].sort(
        key=lambda x:
            x["signal_candle_close_ms"]
    )

    data["summary"] = summary(
        data["observations"]
    )

    data["last_run_utc"] = (
        now.isoformat()
    )

    if data["observations"]:
        data["latest_observation_utc"] = (
            data["observations"][-1][
                "signal_time_utc"
            ]
        )

    # Absolute production safety.
    data["production_changed"] = False

    # --------------------------------------------------------
    # Save cumulative state
    # --------------------------------------------------------

    with open(
        LOG_FILE,
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            data,
            file,
            indent=2,
        )

    latest = (
        data["observations"][-1]
        if data["observations"]
        else None
    )

    print(
        json.dumps(
            {
                "latest_observation": latest,
                "summary": data["summary"],
                "observations":
                    len(data["observations"]),
                "candles_1h":
                    len(hourly),
                "candles_1d":
                    len(daily),
                "forward_test_start_utc":
                    FORWARD_TEST_START_UTC,
                "production_changed":
                    False,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
