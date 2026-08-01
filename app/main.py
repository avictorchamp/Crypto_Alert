from fastapi import FastAPI,Request
import os,requests
from dotenv import load_dotenv
load_dotenv();app=FastAPI();T=os.getenv("TELEGRAM_BOT_TOKEN");C=os.getenv("TELEGRAM_CHAT_ID")
@app.post("/webhook")
async def webhook(req:Request):
 d=await req.json();m=d.get("message","Alert");
 requests.post(f"https://api.telegram.org/bot{T}/sendMessage",json={"chat_id":C,"text":m}) if T and C else None
 return {"ok":True}
