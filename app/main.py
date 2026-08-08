from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.crypto.price import get_market
from app.crypto.analyzer import analyze
from app.scheduler import start_scheduler, scheduler_status
from app.telegram.bot import send_message

VERSION = "2.4.1"


def build_alert_message(result):
    entry = result["entry"]
    tp = result["take_profit"]
    rr = result["risk_reward"]

    return f"""🚨 Crypto Alert V2.4

Coin: {result['coin']}/USDT
Signal: {result['signal']}
Confidence: {result['confidence']}%

Price: {result['price']}
RSI: {result['rsi']}

Entry Zone:
{entry['low']} - {entry['high']}

Stop Loss:
{result['stop_loss']}

TP1:
{tp['tp1']}

TP2:
{tp['tp2']}

Risk/Reward:
{rr if rr is not None else 'N/A'}

Support:
{result['support']}

Resistance:
{result['resistance']}

Reason:
{', '.join(result['reason'])}
""".strip()


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler()
    print("Crypto Alert V2.4 scheduler started: every 5 minutes")
    yield


app = FastAPI(
    title="Crypto Alert",
    version=VERSION,
    lifespan=lifespan
)


@app.get("/")
def root():
    return {
        "service": "Crypto Alert",
        "version": VERSION,
        "status": "running"
    }


@app.get("/scan")
def scan():
    market = get_market()
    alerts = []

    for coin, data in market.items():
        result = analyze(coin, data)
        alerts.append(result)

    return {
        "status": "success",
        "version": VERSION,
        "data": alerts
    }


@app.get("/scheduler")
def scheduler():
    return scheduler_status()
