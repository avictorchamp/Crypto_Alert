def analyze(symbol, price):

    result = {
        "coin": symbol,
        "price": price,
        "signal": "WAIT"
    }


    if symbol == "XRP":

        support = 2.70
        resistance = 3.05


    elif symbol == "ETH":

        support = 3500
        resistance = 4200


    else:

        support = 0
        resistance = 0


    result["support"] = support
    result["resistance"] = resistance


    if price <= support * 1.02:

        result["signal"] = "BUY WATCH"


    elif price >= resistance * 0.98:

        result["signal"] = "SELL WATCH"


    return result
