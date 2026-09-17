def _clamp(value, low=0, high=100):
    return max(low, min(high, int(round(value))))


def generate_signal(
    rsi,
    ema20,
    ema50,
    price,
    support,
    resistance,
    volume_ratio=None,
    momentum_6h=None,
):
    """Production BUY/WAIT strategy.

    Backwards compatible with the previous V2.5.2 six-argument API.
    New confirmations are optional so older callers remain safe.
    """
    bullish_trend = ema20 > ema50
    bearish_trend = ema20 < ema50
    reasons = []
    quality = 0

    # 1. Trend: 25
    if bullish_trend:
        quality += 25
        reasons.append("EMA Bullish Trend")
    elif bearish_trend:
        reasons.append("EMA Bearish Trend")

    # 2. RSI: 20
    if 40 <= rsi <= 55:
        quality += 20
    elif 35 <= rsi < 40 or 55 < rsi <= 65:
        quality += 15
    elif rsi < 35:
        quality += 18
        reasons.append("RSI Oversold")
    elif rsi > 70:
        quality += 5
        reasons.append("RSI Overbought")
    else:
        quality += 10

    entry_low = float(support)
    entry_high = round(support * 1.005, 8)

    distance_to_support = ((price - support) / price) * 100 if price else 999
    near_support = price >= support and distance_to_support <= 1.5

    if near_support:
        quality += 20
        if price <= entry_high:
            reasons.append("Price Near Support")
    elif price >= support and distance_to_support <= 3.0:
        quality += 10

    in_entry_zone = entry_low <= price <= entry_high
    price_above_entry = price > entry_high
    price_below_entry = price < entry_low

    if in_entry_zone:
        quality += 15
    elif price <= entry_high * 1.01:
        quality += 5

    if price_above_entry:
        reasons.append("Price Above Entry Zone")
    if price_below_entry:
        reasons.append("Price Below Entry Zone")

    stop_loss = round(support * 0.99, 8)
    entry_mid = (entry_low + entry_high) / 2
    risk = max(entry_mid - stop_loss, 0.0)

    tp1 = round(float(resistance), 8)
    tp2 = round(max(entry_mid + risk * 2.0, tp1), 8)

    reward_tp1 = max(tp1 - entry_mid, 0.0)
    risk_reward = round(reward_tp1 / risk, 2) if risk > 0 else None

    if risk_reward is not None:
        if risk_reward >= 2.0:
            quality += 20
        elif risk_reward >= 1.5:
            quality += 15
        elif risk_reward >= 1.0:
            quality += 10

    # Optional confirmations. They do not alter the old score when data is absent.
    volume_ok = True
    momentum_ok = True

    if volume_ratio is not None:
        try:
            volume_ratio = float(volume_ratio)
            if volume_ratio >= 1.5:
                quality += 10
                reasons.append("Volume Confirmation")
            elif volume_ratio >= 1.2:
                quality += 5
                reasons.append("Moderate Volume")
            else:
                volume_ok = False
                reasons.append("Weak Volume")
        except (TypeError, ValueError):
            volume_ratio = None

    if momentum_6h is not None:
        try:
            momentum_6h = float(momentum_6h)
            if momentum_6h > 0.005:
                reasons.append("Positive 6H Momentum")
            elif momentum_6h < -0.01:
                momentum_ok = False
                reasons.append("Negative 6H Momentum")
        except (TypeError, ValueError):
            momentum_6h = None

    quality_score = _clamp(quality)
    valid_rr = risk_reward is not None and risk_reward >= 1.0
    strong_rr = risk_reward is not None and risk_reward >= 2.0

    # Volume and momentum are confirmation gates only when their data exists.
    buy_setup = (
        bullish_trend
        and near_support
        and rsi < 65
        and valid_rr
        and quality_score >= 65
        and in_entry_zone
        and volume_ok
        and momentum_ok
    )

    strong_buy = (
        buy_setup
        and strong_rr
        and rsi <= 55
        and quality_score >= 85
    )

    if strong_buy:
        signal = "STRONG BUY"
    elif buy_setup:
        signal = "BUY SETUP"
    elif bearish_trend and rsi > 70:
        signal = "SELL WATCH"
    else:
        signal = "WAIT"

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

    confidence = quality_score
    if signal == "WAIT":
        confidence = min(confidence, 60)
    elif signal == "BUY SETUP":
        confidence = max(65, min(confidence, 84))
    elif signal == "STRONG BUY":
        confidence = max(85, confidence)

    return {
        "signal": signal,
        "confidence": _clamp(confidence),
        "quality_score": quality_score,
        "quality_grade": quality_grade,
        "reason": reasons,
        "entry": {"low": round(entry_low, 8), "high": entry_high},
        "stop_loss": stop_loss,
        "take_profit": {"tp1": tp1, "tp2": tp2},
        "risk_reward": risk_reward,
        "volume_ratio": volume_ratio,
        "momentum_6h": momentum_6h,
    }
