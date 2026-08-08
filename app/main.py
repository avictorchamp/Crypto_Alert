from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.crypto.price import get_market
from app.crypto.analyzer import analyze
from app.scheduler import start_scheduler, scheduler_status

VERSION = "2.3.0"

@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler()
    print("Crypto Alert V2.3 scheduler started: every 5 minutes")
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
        alerts.append(analyze(coin, data))
    return {
        "status": "success",
        "version": VERSION,
        "data": alerts
    }

@app.get("/scheduler")
def scheduler():
    return scheduler_status()
