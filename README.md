# ☕ Tea Tracker Agent

An office tea-tracking Telegram bot with an admin dashboard. Staff log tea by chatting in plain English, Tamil or Tanglish; Gemini parses the intent, and everything is stored in MySQL.

## Features
- **Log:** `mrng 2 tea`, `evng 1 tea`
- **Cancel:** `remove 1 tea`, `undo mrng`, `remove the total teas mrng teas today` (bulk)
- **Query:** `today tea count`, `today mrng tea`, `yesterday tea count`, `oct 2 tea count`, `this month report`
- **Price:** ask for price/bill and get the total at ₹7 per tea (configurable via `TEA_PRICE`)
- Strict slot windows: Morning 10:00–13:00, Evening 15:00–18:00 (logging/cancelling only)
- Duplicate-entry confirmation when another staff member already logged the slot
- Telegram user whitelist
- React admin dashboard: live counters, manual log correction, CSV export

## Stack
FastAPI · SQLAlchemy · MySQL · Google Gemini · Telegram Bot API · React (Vite)

## Setup
```bash
pip install -r requirements.txt
cp .env.example .env     # fill in your values
python main.py           # backend on http://127.0.0.1:8000
```
Leave `TELEGRAM_WEBHOOK_URL` empty for long-polling (local). Set it to a public HTTPS URL for webhook mode.

Dashboard:
```bash
cd frontend
npm install
npm run dev
```
Set `VITE_API_BASE` to the backend URL when hosting.

## Deploy on Vercel
1. Deploy the repo root (backend) and add the variables from `.env.example` in Project Settings → Environment Variables. Don't set `TELEGRAM_WEBHOOK_URL`.
2. Register the webhook once:
   `https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://<your-app>.vercel.app/telegram/webhook&secret_token=<TELEGRAM_WEBHOOK_SECRET>`
3. Deploy `frontend/` as a second Vercel project with `VITE_API_BASE` pointing to the backend.

## Project layout
| File | Purpose |
|---|---|
| `main.py` | FastAPI app, Telegram webhook/polling, dashboard API |
| `bot_logic.py` | Business rules (slots, log, cancel, queries, price) |
| `gemini_agent.py` | Gemini intent/entity extraction prompt |
| `telegram_service.py` | Telegram API helpers |
| `database.py`, `models.py`, `schemas.py` | Database layer |
| `frontend/` | React admin dashboard |
