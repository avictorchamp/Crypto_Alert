from app.crypto.indicators import (
    calculate_rsi,
    calculate_ema,
    support_resistance
)

from app.crypto.strategy import (
    generate_signal
)


def analyze(coin, data):

    prices = data["prices"]

    price = data["price"]

    # -------------------------------------------------
    # Indicators
    # -------------------------------------------------

    rsi = calculate_rsi(
        prices
    )

    ema20 = calculate_ema(
        prices,
        20
    )

    ema50 = calculate_ema(
        prices,
        50
    )

    support, resistance = (
        support_resistance(
            prices
        )
    )

    # -------------------------------------------------
    # Strategy
    # -------------------------------------------------

    result = generate_signal(

        rsi=rsi,

        ema20=ema20,

        ema50=ema50,

        price=price,

        support=support,

        resistance=resistance
    )

    # -------------------------------------------------
    # Final Analysis
    # -------------------------------------------------

    return {

        "coin": coin,

        "price": price,

        "signal": result[
            "signal"
        ],

        "confidence": result[
            "confidence"
        ],

        "quality_score": result[
            "quality_score"
        ],

        "quality_grade": result[
            "quality_grade"
        ],

        "reason": result[
            "reason"
        ],

        "rsi": rsi,

        "ema20": ema20,

        "ema50": ema50,

        "support": support,

        "resistance": resistance,

        "entry": result[
            "entry"
        ],

        "stop_loss": result[
            "stop_loss"
        ],

        "take_profit": result[
            "take_profit"
        ],

        "risk_reward": result[
            "risk_reward"
        ]
    }
