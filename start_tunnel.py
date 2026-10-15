import os
import time
from dotenv import load_dotenv
from pyngrok import ngrok

load_dotenv()
token = os.getenv("NGROK_AUTHTOKEN")
if not token:
    raise SystemExit("Set NGROK_AUTHTOKEN in .env first")

ngrok.set_auth_token(token)
tunnel = ngrok.connect(8000, "http")
url = tunnel.public_url
print("\nPublic URL     :", url)
print("Telegram hook  :", url + "/telegram/webhook")
print("\nTo use webhook mode, put this in .env and restart main.py:")
print(f"  TELEGRAM_WEBHOOK_URL={url}")
print("(Not required — with TELEGRAM_WEBHOOK_URL empty the bot uses polling.)")
print("\nKeep this window open. Press Ctrl+C to stop.")
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    ngrok.kill()
