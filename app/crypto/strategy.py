def _clamp(value, low=0, high=100):
    return max(low, min(high, int(round(value))))

def generate_signal(rsi, ema20, ema50, price, support, resistance):
    bullish_trend = ema20 > ema50
    bearish_trend = ema20 < ema50
    reasons = []
    score = 50

    if bullish_trend:
        score += 15
        reasons.append("EMA Bullish Trend")
    elif bearish_trend:
        score -= 10
        reasons.append("EMA Bearish Trend")

    if rsi < 35:
        score += 10
        reasons.append("RSI Oversold")
    elif rsi > 70:
        score -= 15
        reasons.append("RSI Overbought")

    entry_low = float(support)
    entry_high = round(support * 1.005, 8)

    near_support = (
        price >= support and
        ((price - support) / price * 100) <= 1.5
    )

    if near_support:
        score += 15
        reasons.append("Price Near Support")

    stop_loss = round(support * 0.99, 8)
    entry_mid = (entry_low + entry_high) / 2
    risk = max(entry_mid - stop_loss, 0.0)

    tp1 = round(float(resistance), 8)
    # For long setups, TP2 must never be below TP1.
    tp2 = round(max(entry_mid + risk * 2.0, tp1), 8)

    reward_tp1 = max(tp1 - entry_mid, 0.0)
    risk_reward = round(reward_tp1 / risk, 2) if risk > 0 else None

    valid_rr = risk_reward is not None and risk_reward >= 1.0
    strong_rr = risk_reward is not None and risk_reward >= 2.0

    buy_setup = bullish_trend and near_support and rsi < 65 and valid_rr
    strong_buy = buy_setup and strong_rr and rsi <= 55

    if strong_buy:
        signal = "STRONG BUY"
    elif buy_setup:
        signal = "BUY SETUP"
    elif bearish_trend and rsi > 70:
        signal = "SELL WATCH"
    else:
        signal = "WAIT"

    confidence = _clamp(score)
    if signal == "WAIT":
        confidence = min(confidence, 60)
    elif signal == "BUY SETUP":
        confidence = max(confidence, 65)
    elif signal == "STRONG BUY":
        confidence = max(confidence, 75)

    return {
        "signal": signal,
        "confidence": confidence,
        "reason": reasons,
        "entry": {"low": round(entry_low, 8), "high": round(entry_high, 8)},
        "stop_loss": stop_loss,
        "take_profit": {"tp1": tp1, "tp2": tp2},
        "risk_reward": risk_reward
    }
