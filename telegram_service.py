import os
import httpx
from dotenv import load_dotenv

load_dotenv()


def _api_url(method: str) -> str:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured in .env")
    return f"https://api.telegram.org/bot{token}/{method}"


async def _call(method: str, payload: dict | None = None, timeout: float = 15.0):
    """Call a Telegram Bot API method and return its `result` (or None on failure)."""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(_api_url(method), json=payload or {}, timeout=timeout)
            data = response.json()
            if not data.get("ok"):
                print(f"❌ Telegram API error on {method}: {data}")
                return None
            return data.get("result")
        except httpx.ReadTimeout:
            # Normal for long-polling when no updates arrive in time
            return None
        except Exception as e:
            print(f"❌ Network error calling Telegram {method}: {e}")
            return None


async def send_telegram_message(chat_id: int | str, text: str, reply_to: int | None = None):
    payload = {"chat_id": chat_id, "text": text}
    if reply_to:
        payload["reply_parameters"] = {"message_id": reply_to, "allow_sending_without_reply": True}
    result = await _call("sendMessage", payload)
    print(f"📤 Sent reply to chat {chat_id}: {'ok' if result else 'FAILED'}")
    return result


async def get_updates(offset: int | None = None, timeout: int = 30) -> list:
    payload = {"timeout": timeout, "allowed_updates": ["message"]}
    if offset is not None:
        payload["offset"] = offset
    # HTTP timeout must exceed Telegram's long-poll timeout
    return await _call("getUpdates", payload, timeout=timeout + 10) or []


async def set_webhook(url: str, secret_token: str | None = None):
    payload = {"url": url, "allowed_updates": ["message"], "drop_pending_updates": False}
    if secret_token:
        payload["secret_token"] = secret_token
    return await _call("setWebhook", payload)


async def delete_webhook():
    return await _call("deleteWebhook", {"drop_pending_updates": False})


async def set_bot_commands():
    commands = [
        {"command": "start", "description": "Welcome & how to use"},
        {"command": "help", "description": "Show example messages"},
        {"command": "total", "description": "This month's tea summary"},
    ]
    return await _call("setMyCommands", {"commands": commands})


async def get_me():
    return await _call("getMe")
