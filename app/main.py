from fastapi import FastAPI

from app.crypto.price import get_market
from app.crypto.analyzer import analyze
from app.telegram.bot import send_message

from app.config import VERSION
from app.logger import logger


app = FastAPI(
    title="Crypto Alert",
    version="2.2.0"
)


@app.get("/")
def root():

    return {
        "service": "Crypto Alert",
        "version": "2.2.0",
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

    market=get_market()

    alerts=[]


    for coin,data in market.items():

        result=analyze(
            coin,
            data
        )


        alerts.append(result)


        if result["signal"]!="WAIT":

            msg=f"""
🚨 Crypto Alert V2.2

Coin:
{coin}/USDT

Price:
{result['price']}

Signal:
{result['signal']}

Confidence:
{result['confidence']}%

RSI:
{result['rsi']}

Reason:
{', '.join(result['reason'])}

Support:
{result['support']}

Resistance:
{result['resistance']}
"""

            send_message(msg)


    return {
        "status":"success",
        "version":"2.2.0",
        "data":alerts
    }
