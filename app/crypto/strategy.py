def _clamp(value, low=0, high=100):
    return max(low, min(high, int(round(value))))


def generate_signal(rsi, ema20, ema50, price, support, resistance):
    score = 50
    reasons = []

    bullish_trend = ema20 > ema50
    bearish_trend = ema20 < ema50

    if bullish_trend:
        score += 15
        reasons.append("EMA Bullish Trend")
    elif bearish_trend:
        score -= 10
        reasons.append("EMA Bearish Trend")

    if rsi < 35:
        score += 15
        reasons.append("RSI Oversold")
    elif rsi > 70:
        score -= 15
        reasons.append("RSI Overbought")

    # Distance from support/resistance as a percentage.
    support_distance = ((price - support) / price * 100) if price else 999
    resistance_distance = ((resistance - price) / price * 100) if price else 999

    near_support = 0 <= support_distance <= 1.5
    near_resistance = 0 <= resistance_distance <= 1.5

    if near_support and bullish_trend and rsi < 65:
        score += 15
        reasons.append("Price Near Support")
    elif near_resistance:
        score -= 5
        reasons.append("Near Resistance")

    confidence = _clamp(score)

    # BUY SETUP: trend + price near support + RSI not overbought.
    buy_setup = bullish_trend and near_support and rsi < 65

    # STRONG BUY requires an additional RSI/momentum confirmation.
    strong_buy = buy_setup and rsi <= 50

    if strong_buy:
        signal = "STRONG BUY"
    elif buy_setup:
        signal = "BUY SETUP"
    elif bearish_trend and rsi > 70:
        signal = "SELL WATCH"
    else:
        signal = "WAIT"

    entry_low = round(support * 1.000, 8)
    entry_high = round(support * 1.015, 8)

    # Volatility-free first version: SL below support by 1%.
    stop_loss = round(support * 0.99, 8)

    # TP1 at resistance; TP2 extends the same risk distance.
    risk = max(entry_high - stop_loss, 0)
    take_profit_1 = round(resistance, 8)
    take_profit_2 = round(entry_high + (risk * 2.0), 8)

    risk_reward = None
    if entry_high > stop_loss and take_profit_1 > entry_high:
        risk_reward = round(
            (take_profit_1 - entry_high) / (entry_high - stop_loss), 2
        )

    return {
        "signal": signal,
        "confidence": confidence,
        "reason": reasons,
        "entry": {
            "low": entry_low,
            "high": entry_high
        },
        "stop_loss": stop_loss,
        "take_profit": {
            "tp1": take_profit_1,
            "tp2": take_profit_2
        },
        "risk_reward": risk_reward
    }
