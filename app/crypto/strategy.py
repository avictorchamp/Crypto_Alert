def generate_signal(
    rsi,
    ema20,
    ema50
):

    score = 50

    reasons=[]


    if rsi < 35:

        score += 15
        reasons.append(
            "RSI Oversold"
        )


    if rsi > 70:

        score -= 15
        reasons.append(
            "RSI Overbought"
        )


    if ema20 > ema50:

        score += 15

        reasons.append(
            "EMA Bullish Trend"
        )


    else:

        score -= 10

        reasons.append(
            "EMA Bearish Trend"
        )


    if score >= 70:

        signal="BUY WATCH"


    elif score <=30:

        signal="SELL WATCH"


    else:

        signal="WAIT"



    return {

        "signal":signal,

        "confidence":score,

        "reason":reasons

    }
