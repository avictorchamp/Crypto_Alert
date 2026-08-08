def _clamp(value, low=0, high=100):
    return max(low, min(high, int(round(value))))


def generate_signal(rsi, ema20, ema50, price, support, resistance):

    bullish_trend = ema20 > ema50
    bearish_trend = ema20 < ema50

    reasons = []

    # =================================================
    # V2.5.2 QUALITY SCORE
    #
    # Trend              = 25
    # RSI                = 20
    # Support            = 20
    # Entry Quality      = 15
    # Risk/Reward        = 20
    # Total              = 100
    # =================================================

    quality = 0

    # =================================================
    # 1. EMA TREND
    # =================================================

    if bullish_trend:

        quality += 25

        reasons.append(
            "EMA Bullish Trend"
        )

    elif bearish_trend:

        reasons.append(
            "EMA Bearish Trend"
        )

    # =================================================
    # 2. RSI
    # =================================================

    if 40 <= rsi <= 55:

        quality += 20

    elif 35 <= rsi < 40 or 55 < rsi <= 65:

        quality += 15

    elif rsi < 35:

        quality += 18

        reasons.append(
            "RSI Oversold"
        )

    elif rsi > 70:

        quality += 5

        reasons.append(
            "RSI Overbought"
        )

    else:

        quality += 10

    # =================================================
    # 3. ENTRY ZONE
    # =================================================

    entry_low = float(support)

    entry_high = round(
        support * 1.005,
        8
    )

    # =================================================
    # 4. SUPPORT PROXIMITY
    # =================================================

    distance_to_support = (
        ((price - support) / price) * 100
        if price
        else 999
    )

    near_support = (
        price >= support
        and distance_to_support <= 1.5
    )

    if near_support:

        quality += 20

        # Don't duplicate this reason if price
        # has already moved above the entry zone.

        if price <= entry_high:

            reasons.append(
                "Price Near Support"
            )

    elif (
        price >= support
        and distance_to_support <= 3.0
    ):

        quality += 10

    # =================================================
    # 5. STRICT ENTRY TIMING
    # =================================================

    # V2.5.2:
    #
    # BUY SETUP is allowed ONLY when:
    #
    # entry_low <= price <= entry_high
    #
    # No 1% tolerance.
    # No 2% tolerance.
    #
    # Once price moves above entry_high,
    # the setup is considered late.

    in_entry_zone = (
        entry_low <= price <= entry_high
    )

    price_above_entry = (
        price > entry_high
    )

    price_below_entry = (
        price < entry_low
    )

    # =================================================
    # ENTRY QUALITY SCORE
    # =================================================

    if in_entry_zone:

        quality += 15

    elif price <= entry_high * 1.01:

        # Small amount of score can remain for
        # quality calculation, but this DOES NOT
        # permit BUY SETUP.

        quality += 5

    # =================================================
    # PRICE ABOVE ENTRY ZONE
    # =================================================

    if price_above_entry:

        reasons.append(
            "Price Above Entry Zone"
        )

    # =================================================
    # PRICE BELOW ENTRY ZONE
    # =================================================

    if price_below_entry:

        reasons.append(
            "Price Below Entry Zone"
        )

    # =================================================
    # 6. STOP LOSS
    # =================================================

    stop_loss = round(
        support * 0.99,
        8
    )

    entry_mid = (
        entry_low + entry_high
    ) / 2

    risk = max(
        entry_mid - stop_loss,
        0.0
    )

    # =================================================
    # 7. TAKE PROFIT
    # =================================================

    tp1 = round(
        float(resistance),
        8
    )

    # TP2 must NEVER be below TP1.

    tp2 = round(
        max(
            entry_mid + risk * 2.0,
            tp1
        ),
        8
    )

    # =================================================
    # 8. RISK / REWARD
    # =================================================

    reward_tp1 = max(
        tp1 - entry_mid,
        0.0
    )

    if risk > 0:

        risk_reward = round(
            reward_tp1 / risk,
            2
        )

    else:

        risk_reward = None

    # =================================================
    # 9. RISK / REWARD SCORE
    # =================================================

    if risk_reward is not None:

        if risk_reward >= 2.0:

            quality += 20

        elif risk_reward >= 1.5:

            quality += 15

        elif risk_reward >= 1.0:

            quality += 10

    # =================================================
    # FINAL QUALITY SCORE
    # =================================================

    quality_score = _clamp(
        quality
    )

    # =================================================
    # SIGNAL CONDITIONS
    # =================================================

    valid_rr = (
        risk_reward is not None
        and risk_reward >= 1.0
    )

    strong_rr = (
        risk_reward is not None
        and risk_reward >= 2.0
    )

    # =================================================
    # BUY SETUP
    #
    # IMPORTANT:
    # Price MUST actually be inside Entry Zone.
    # =================================================

    buy_setup = (

        bullish_trend

        and near_support

        and rsi < 65

        and valid_rr

        and quality_score >= 65

        and in_entry_zone
    )

    # =================================================
    # STRONG BUY
    # =================================================

    strong_buy = (

        buy_setup

        and strong_rr

        and rsi <= 55

        and quality_score >= 85
    )

    # =================================================
    # SIGNAL
    # =================================================

    if strong_buy:

        signal = "STRONG BUY"

    elif buy_setup:

        signal = "BUY SETUP"

    elif bearish_trend and rsi > 70:

        signal = "SELL WATCH"

    else:

        signal = "WAIT"

    # =================================================
    # QUALITY GRADE
    # =================================================

    if quality_score >= 85:

        quality_grade = "A"

    elif quality_score >= 75:

        quality_grade = "B"

    elif quality_score >= 65:

        quality_grade = "C"

    elif quality_score >= 45:

        quality_grade = "D"

    else:

        quality_grade = "F"

    # =================================================
    # CONFIDENCE
    # =================================================

    confidence = quality_score

    if signal == "WAIT":

        confidence = min(
            confidence,
            60
        )

    elif signal == "BUY SETUP":

        confidence = max(
            65,
            min(
                confidence,
                84
            )
        )

    elif signal == "STRONG BUY":

        confidence = max(
            85,
            confidence
        )

    # =================================================
    # RESULT
    # =================================================

    return {

        "signal": signal,

        "confidence": _clamp(
            confidence
        ),

        "quality_score": quality_score,

        "quality_grade": quality_grade,

        "reason": reasons,

        "entry": {

            "low": round(
                entry_low,
                8
            ),

            "high": round(
                entry_high,
                8
            )
        },

        "stop_loss": stop_loss,

        "take_profit": {

            "tp1": tp1,

            "tp2": tp2
        },

        "risk_reward": risk_reward
    }
