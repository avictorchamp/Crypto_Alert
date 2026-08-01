from fastapi import FastAPI

from app.crypto.price import get_market
from app.crypto.analyzer import analyze
from app.telegram.bot import send_message

from app.config import VERSION
from app.logger import logger


app = FastAPI(
    title="Crypto Alert",
    version="2.1.0"
)


@app.get("/")
def root():

    return {
        "service": "Crypto Alert",
        "version": "2.1.0",
        "status": "running"
    }


@app.get("/health")
def health():

    return {
        "status": "healthy",
        "version": VERSION
    }


@app.get("/scan")
def scan():

    try:

        market = get_market()

        alerts = []


        for coin, price in market.items():

            result = analyze(
                coin,
                price
            )

            alerts.append(result)


            if result["signal"] != "WAIT":

                msg = f"""
🚨 Crypto Alert

Coin: {coin}/USDT

Price:
{price}

Signal:
{result['signal']}

Support:
{result['support']}

Resistance:
{result['resistance']}
"""

                send_message(msg)


        return {
            "status": "success",
            "data": alerts
        }


    except Exception as e:

        logger.error(
            f"Scanner error: {e}"
        )

        return {
            "status": "error",
            "message": str(e)
        }
