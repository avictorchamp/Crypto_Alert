from app.crypto.indicators import (
    calculate_rsi,
    calculate_ema,
    support_resistance
)

from app.crypto.strategy import (
    generate_signal
)



def analyze(
    coin,
    data
):


    prices=data["prices"]


    price=data["price"]


    rsi=calculate_rsi(
        prices
    )


    ema20=calculate_ema(
        prices,
        20
    )


    ema50=calculate_ema(
        prices,
        50
    )


    support,resistance = support_resistance(
        prices
    )


    result=generate_signal(
        rsi,
        ema20,
        ema50
    )


    return {

        "coin":coin,

        "price":price,

        "signal":
            result["signal"],

        "confidence":
            result["confidence"],

        "reason":
            result["reason"],

        "rsi":rsi,

        "ema20":ema20,

        "ema50":ema50,

        "support":support,

        "resistance":resistance

    }
