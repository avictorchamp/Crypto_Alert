def calculate_ema(prices, period):

    if len(prices) < period:
        return 0

    multiplier = 2 / (period + 1)

    ema = prices[0]

    for price in prices[1:]:
        ema = (
            price * multiplier
            +
            ema * (1 - multiplier)
        )

    return round(ema, 2)



def calculate_rsi(prices, period=14):

    if len(prices) <= period:
        return 50


    gains = []
    losses = []


    for i in range(1, len(prices)):

        change = prices[i] - prices[i-1]

        if change >= 0:
            gains.append(change)
            losses.append(0)

        else:
            gains.append(0)
            losses.append(abs(change))


    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period


    if avg_loss == 0:
        return 100


    rs = avg_gain / avg_loss

    rsi = 100 - (
        100 /
        (1 + rs)
    )


    return round(rsi,2)



def support_resistance(prices):

    support = min(prices)

    resistance = max(prices)


    return (
        round(support,2),
        round(resistance,2)
    )
