from fastapi import FastAPI

from app.config import VERSION
from app.logger import logger


app = FastAPI(
    title="Crypto Alert",
    version=VERSION
)


@app.get("/")
def root():
    return {
        "service": "Crypto Alert",
        "version": VERSION,
        "status": "running"
    }


@app.get("/health")
def health():
    return {
        "status": "healthy"
    }


@app.on_event("startup")
async def startup():
    logger.info(
        f"Crypto Alert {VERSION} started"
    )
