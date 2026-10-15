import os
import sys
import csv
import io
import asyncio

# Windows consoles default to cp1252, which crashes on emoji in log output
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
from contextlib import asynccontextmanager
from datetime import date
from fastapi import FastAPI, Request, Header, Depends, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
import uvicorn
from dotenv import load_dotenv

from database import engine, Base, get_db, SessionLocal
from models import TeaLog
from schemas import TeaLogCreate, TeaLogUpdate
from bot_logic import build_reply
from telegram_service import (
    send_telegram_message,
    get_updates,
    set_webhook,
    delete_webhook,
    set_bot_commands,
    get_me,
)

load_dotenv()
Base.metadata.create_all(bind=engine)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
# If set (e.g. your ngrok https URL), the bot runs in webhook mode.
# If empty, the bot uses long-polling — no public URL / tunnel needed.
TELEGRAM_WEBHOOK_URL = os.getenv("TELEGRAM_WEBHOOK_URL", "").strip().rstrip("/")
TELEGRAM_WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
# Comma-separated Telegram user IDs allowed to use the bot. Everyone else is ignored silently.
ALLOWED_USER_IDS = {
    uid.strip() for uid in os.getenv("ALLOWED_TELEGRAM_USER_IDS", "").split(",") if uid.strip()
}


async def telegram_polling_loop():
    """Long-poll Telegram for new messages (used when no webhook URL is configured)."""
    offset = None
    print("🤖 Telegram bot started in POLLING mode")
    while True:
        try:
            updates = await get_updates(offset, timeout=30)
            for update in updates:
                offset = update["update_id"] + 1
                try:
                    await handle_telegram_update(update)
                except Exception as e:
                    print("Telegram update handling error:", e)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print("Telegram polling error:", e)
            await asyncio.sleep(5)


@asynccontextmanager
async def lifespan(app: FastAPI):
    polling_task = None
    if not TELEGRAM_BOT_TOKEN:
        print("⚠️ TELEGRAM_BOT_TOKEN not set — Telegram bot is disabled.")
    else:
        if ALLOWED_USER_IDS:
            print(f"🔒 Whitelist active: {len(ALLOWED_USER_IDS)} allowed user(s)")
        else:
            print("⚠️ ALLOWED_TELEGRAM_USER_IDS is empty — ALL messages will be ignored.")
        me = await get_me()
        if me:
            print(f"✅ Connected to Telegram as @{me.get('username')}")
        await set_bot_commands()
        if TELEGRAM_WEBHOOK_URL:
            hook = f"{TELEGRAM_WEBHOOK_URL}/telegram/webhook"
            ok = await set_webhook(hook, TELEGRAM_WEBHOOK_SECRET or None)
            print(f"🤖 Telegram bot in WEBHOOK mode → {hook} ({'ok' if ok else 'FAILED'})")
        else:
            # getUpdates doesn't work while a webhook is registered
            await delete_webhook()
            polling_task = asyncio.create_task(telegram_polling_loop())
    yield
    if polling_task:
        polling_task.cancel()


app = FastAPI(title="Telegram Tea Tracker & Admin Dashboard", lifespan=lifespan)

# Enable CORS for local React development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- TELEGRAM BOT ---

async def handle_telegram_update(update: dict):
    msg = update.get("message")
    if not msg:
        return
    chat_id = msg["chat"]["id"]
    sender = msg.get("from", {})
    user_id = str(sender.get("id", ""))
    user_name = " ".join(filter(None, [sender.get("first_name"), sender.get("last_name")])) \
        or sender.get("username") or "Staff"

    # Whitelist: silently drop anyone not explicitly allowed
    if user_id not in ALLOWED_USER_IDS:
        print(f"🚫 Ignored message from non-whitelisted user {user_id} ({user_name})")
        return

    text_body = (msg.get("text") or "").strip()
    if not text_body:
        await send_telegram_message(chat_id, "✍️ Please send a text message, e.g. 'mrng 2 tea'.")
        return

    print(f"📩 Incoming Telegram message from {user_id} ({user_name}): '{text_body}'")

    try:
        reply = await asyncio.to_thread(build_reply, user_id, user_name, text_body)
    except Exception as e:
        print("Bot processing error:", e)
        reply = "⚠️ Sorry, something went wrong. Please try again."

    await send_telegram_message(chat_id, reply, reply_to=msg.get("message_id"))


@app.post("/telegram/webhook")
async def telegram_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_telegram_bot_api_secret_token: str | None = Header(None),
):
    """Receives updates when running in webhook mode (TELEGRAM_WEBHOOK_URL set)."""
    if TELEGRAM_WEBHOOK_SECRET and x_telegram_bot_api_secret_token != TELEGRAM_WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Invalid secret token")
    update = await request.json()
    # Serverless hosts (Vercel) freeze the function once the response is sent,
    # so process the update BEFORE replying instead of in a background task.
    try:
        await handle_telegram_update(update)
    except Exception as e:
        print("Telegram update handling error:", e)
    return {"ok": True}

# --- DASHBOARD REST API ENDPOINTS ---

@app.get("/api/dashboard/stats")
def get_dashboard_stats(db: Session = Depends(get_db)):
    """Live Counter Card Breakdown for Today"""
    today = date.today()
    morning_count = db.query(func.sum(TeaLog.count)).filter(
        TeaLog.date == today, TeaLog.session == "morning"
    ).scalar() or 0

    evening_count = db.query(func.sum(TeaLog.count)).filter(
        TeaLog.date == today, TeaLog.session == "evening"
    ).scalar() or 0

    month_total = db.query(func.sum(TeaLog.count)).filter(
        func.extract("year", TeaLog.date) == today.year,
        func.extract("month", TeaLog.date) == today.month
    ).scalar() or 0

    return {
        "today_total": morning_count + evening_count,
        "morning_total": morning_count,
        "evening_total": evening_count,
        "month_total": month_total,
        "date": today.isoformat()
    }

@app.get("/api/dashboard/logs")
def get_recent_logs(limit: int = 50, db: Session = Depends(get_db)):
    """Fetch logs for Manual Correction Suite"""
    return db.query(TeaLog).order_by(TeaLog.date.desc(), TeaLog.id.desc()).limit(limit).all()

@app.delete("/api/dashboard/logs/{log_id}")
def delete_log(log_id: int, db: Session = Depends(get_db)):
    """Manual Correction: Remove accidental duplicate entry"""
    record = db.query(TeaLog).filter(TeaLog.id == log_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Record not found")
    db.delete(record)
    db.commit()
    return {"status": "deleted", "id": log_id}

@app.get("/api/dashboard/export-csv")
def export_csv(month: int = None, year: int = None, db: Session = Depends(get_db)):
    """Export monthly logs to CSV for vendor invoicing"""
    target_year = year or date.today().year
    target_month = month or date.today().month

    logs = db.query(TeaLog).filter(
        func.extract("year", TeaLog.date) == target_year,
        func.extract("month", TeaLog.date) == target_month
    ).order_by(TeaLog.date.asc()).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Date", "Staff Name", "Telegram ID", "Session", "Cups"])

    for item in logs:
        writer.writerow([item.id, item.date, item.user_name, item.phone_number, item.session, item.count])

    output.seek(0)
    filename = f"tea_report_{target_year}_{target_month:02d}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
