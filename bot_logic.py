"""Telegram tea-bot business rules.

- Strict time windows (Morning 10:00-13:00, Evening 15:00-18:00)
- Duplicate safeguard: confirm before adding to a slot someone else already logged
- Cancel / undo only inside the active slot
- Non-tea messages are rejected
"""
import os
import re
import threading
from dataclasses import dataclass
from datetime import datetime, date, time, timedelta

from sqlalchemy import func

from database import SessionLocal
from models import TeaLog
from gemini_agent import parse_user_message

try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo(os.getenv("BOT_TIMEZONE", "Asia/Kolkata"))
except Exception:
    TZ = None  # tzdata missing -> fall back to the machine's local time

# session -> (start inclusive, end exclusive)
SLOTS = {
    "morning": (time(10, 0), time(13, 0)),
    "evening": (time(15, 0), time(18, 0)),
}
SLOT_TIMINGS_TEXT = "🕙 Morning: 10:00 AM – 1:00 PM\n🕒 Evening: 3:00 PM – 6:00 PM"
MAX_CUPS_PER_ENTRY = 50
TEA_PRICE = int(os.getenv("TEA_PRICE", 7))  # rupees per tea
CONFIRM_TIMEOUT = timedelta(minutes=10)

HELP_TEXT = (
    "☕ DP Silks Tea Tracker\n\n"
    "Send messages like:\n"
    "• mrng 2 tea\n"
    "• evng 1 tea\n"
    "• cancel evng tea  /  remove 1 tea\n"
    "• give total this month  (or /total)\n\n"
    f"Logging & cancelling only work during:\n{SLOT_TIMINGS_TEXT}\n\n"
    "English, Tamil or Tanglish all work."
)
REJECT_TEXT = (
    "🚫 I only handle tea entries.\n"
    "Examples: 'mrng 2 tea', 'cancel evng tea', 'this month total'.\n"
    "Type /help for details."
)

YES_WORDS = {"yes", "y", "yeah", "yep", "ok", "okay", "confirm", "sure", "aama", "ama", "haan", "s"}
NO_WORDS = {"no", "n", "nope", "cancel", "venam", "vendam", "illa", "vena"}

# ---- local fast-path vocabulary (saves Gemini quota for simple messages) ----
_SESSION_WORDS = {
    **dict.fromkeys(["mrng", "morning", "morn", "mng", "kalaila", "kaalai", "kalai", "kaalaila"], "morning"),
    **dict.fromkeys(["evng", "evening", "eve", "evg", "evn", "maalai", "malai", "saayankalam"], "evening"),
}
_NUMBER_WORDS = {"one": 1, "oru": 1, "onnu": 1, "two": 2, "rendu": 2, "three": 3, "moonu": 3,
                 "four": 4, "naalu": 4, "five": 5, "anju": 5}
_TEA_WORDS = {"tea", "teas", "chai", "cup", "cups"}
_CANCEL_WORDS = {"cancel", "remove", "delete", "undo", "minus"}
# NOTE: 'today' is deliberately NOT filler - 'today mrng tea' is a query, handled by Gemini.
_FILLER_WORDS = {"podu", "add", "log", "for", "please", "pls", "plz", "the", "my", "a", "x"}
_SUMMARY_PHRASES = {
    "total": "current_month", "report": "current_month", "summary": "current_month",
    "month total": "current_month", "this month total": "current_month",
    "today total": "today", "today tea count": "today", "yesterday total": "yesterday",
    "yesterday tea count": "yesterday",
}


@dataclass
class PendingLog:
    session: str
    count: int
    day: date
    expires_at: datetime


_pending: dict[str, PendingLog] = {}
_pending_lock = threading.Lock()


# ---------- helpers ----------

def now() -> datetime:
    return datetime.now(TZ) if TZ else datetime.now()


def active_slot(dt: datetime) -> str | None:
    t = dt.time()
    for name, (start, end) in SLOTS.items():
        if start <= t < end:
            return name
    return None


def slot_end(dt: datetime, session: str) -> datetime:
    return datetime.combine(dt.date(), SLOTS[session][1], tzinfo=dt.tzinfo)


def teas(n: int) -> str:
    return f"{n} tea" if n == 1 else f"{n} teas"


def _normalize_reply(text: str) -> str:
    return re.sub(r"[^\w\s]", "", text.lower()).strip()


def _closed_text(action: str) -> str:
    verb = "Logging" if action == "log" else "Cancelling"
    return f"⏰ {verb} tea is closed right now.\nValid slot timings:\n{SLOT_TIMINGS_TEXT}"


def local_parse(text: str) -> dict | None:
    """Parse simple messages like 'mrng 2 tea' / 'cancel evng tea' without the LLM.
    Returns None if the text contains anything we don't recognise (-> ask Gemini)."""
    norm = _normalize_reply(text)
    if norm in _SUMMARY_PHRASES:
        return {"action": "query", "session": None, "count": None,
                "date_target": _SUMMARY_PHRASES[norm], "include_price": False}

    # split '2tea' -> '2 tea'
    tokens = re.sub(r"(\d+)", r" \1 ", norm).split()
    session, count, has_tea, has_cancel = None, None, False, False
    for tok in tokens:
        if tok in _SESSION_WORDS:
            if session and session != _SESSION_WORDS[tok]:
                return None
            session = _SESSION_WORDS[tok]
        elif tok.isdigit() or tok in _NUMBER_WORDS:
            if count is not None:
                return None
            count = int(tok) if tok.isdigit() else _NUMBER_WORDS[tok]
        elif tok in _TEA_WORDS:
            has_tea = True
        elif tok in _CANCEL_WORDS:
            has_cancel = True
        elif tok not in _FILLER_WORDS:
            return None
    if has_cancel:
        return {"action": "cancel", "session": session, "count": count, "bulk_remove": False}
    if has_tea:
        return {"action": "log", "session": session, "count": count}
    return None


# ---------- DB actions ----------

def _record(user_id: str, user_name: str, session: str, count: int, day: date) -> str:
    db = SessionLocal()
    try:
        db.add(TeaLog(phone_number=user_id, user_name=user_name, session=session, count=count, date=day))
        db.commit()
        slot_total = db.query(func.sum(TeaLog.count)).filter(
            TeaLog.date == day, TeaLog.session == session
        ).scalar() or 0
        my_total = db.query(func.sum(TeaLog.count)).filter(
            TeaLog.phone_number == user_id, TeaLog.date == day
        ).scalar() or 0
        return (
            f"☕ Recorded {teas(count)} for {session.capitalize()}.\n"
            f"{session.capitalize()} total (all staff): {teas(int(slot_total))}\n"
            f"Your total today: {teas(int(my_total))}"
        )
    finally:
        db.close()


def _handle_log(user_id: str, user_name: str, session: str, count: int, current: datetime) -> str:
    today = current.date()
    db = SessionLocal()
    try:
        others = db.query(TeaLog.user_name, func.sum(TeaLog.count)).filter(
            TeaLog.date == today,
            TeaLog.session == session,
            TeaLog.phone_number != user_id,
        ).group_by(TeaLog.phone_number, TeaLog.user_name).all()
    finally:
        db.close()

    if not others:
        return _record(user_id, user_name, session, count, today)

    with _pending_lock:
        _pending[user_id] = PendingLog(
            session=session,
            count=count,
            day=today,
            expires_at=min(current + CONFIRM_TIMEOUT, slot_end(current, session)),
        )
    who = " and ".join(f"{name} already logged {teas(int(n or 0))}" for name, n in others)
    return (
        f"⚠️ {who} for {session.capitalize()}.\n"
        f"Do you also want to add {teas(count)}? Reply 'yes' to confirm or 'no' to cancel."
    )


def _handle_cancel(user_id: str, session: str, count: int | None, day: date, bulk: bool = False) -> str:
    db = SessionLocal()
    try:
        records = db.query(TeaLog).filter(
            TeaLog.phone_number == user_id,
            TeaLog.date == day,
            TeaLog.session == session,
        ).order_by(TeaLog.id.desc()).all()
        if not records:
            return f"⚠️ You have no {session.capitalize()} tea entries today to cancel."

        if bulk:
            # Remove ALL of this user's entries for the session today
            removed = sum(r.count for r in records)
            for rec in records:
                db.delete(rec)
        elif count is None:
            # No number given -> undo the latest entry
            removed = records[0].count
            db.delete(records[0])
        else:
            remaining = count
            for rec in records:
                if remaining <= 0:
                    break
                if rec.count <= remaining:
                    remaining -= rec.count
                    db.delete(rec)
                else:
                    rec.count -= remaining
                    remaining = 0
            removed = count - remaining
        db.commit()

        left = db.query(func.sum(TeaLog.count)).filter(
            TeaLog.phone_number == user_id,
            TeaLog.date == day,
            TeaLog.session == session,
        ).scalar() or 0
        return (
            f"🗑️ Removed {teas(removed)} from {session.capitalize()}.\n"
            f"Your {session.capitalize()} total is now {teas(int(left))}."
        )
    finally:
        db.close()


def _price_line(n: int) -> str:
    return f"💰 Total price: ₹{n * TEA_PRICE} ({n} × ₹{TEA_PRICE})"


def _parse_date_str(s: str | None, today: date) -> date | None:
    if not s:
        return None
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    for fmt in ("%b %d", "%B %d", "%d %b", "%d %B"):
        try:
            p = datetime.strptime(s, fmt)
            return date(today.year, p.month, p.day)
        except ValueError:
            pass
    return None


def _day_query(user_id: str, day: date, session: str | None, include_price: bool, label: str) -> str:
    db = SessionLocal()
    try:
        q = db.query(TeaLog.session, func.sum(TeaLog.count)).filter(
            TeaLog.phone_number == user_id, TeaLog.date == day,
        )
        if session:
            q = q.filter(TeaLog.session == session)
        rows = q.group_by(TeaLog.session).all()
    finally:
        db.close()

    by_sess = {s: int(n or 0) for s, n in rows}
    total = sum(by_sess.values())
    if session:
        lines = [f"📊 {label} {session.capitalize()}: {teas(total)}"]
    else:
        lines = [
            f"📊 {label}: {teas(total)}",
            f"Morning: {by_sess.get('morning', 0)}, Evening: {by_sess.get('evening', 0)}",
        ]
    if include_price:
        lines.append(_price_line(total))
    return "\n".join(lines)


def _query(user_id: str, parsed: dict, today: date) -> str:
    target = parsed.get("date_target") or "today"
    session = parsed.get("session")
    price = bool(parsed.get("include_price"))
    if target == "current_month":
        return _summary(user_id, today, price)
    if target == "yesterday":
        day = today - timedelta(days=1)
    elif target == "specific_date":
        day = _parse_date_str(parsed.get("target_date_str"), today)
        if day is None:
            return "⚠️ I couldn't understand that date. Try 'oct 2 tea count'."
    else:
        day = today
    label = "Today" if day == today else ("Yesterday" if target == "yesterday" else day.strftime("%d %b"))
    return _day_query(user_id, day, session, price, label)


def _summary(user_id: str, today: date, include_price: bool = False) -> str:
    db = SessionLocal()
    try:
        records = db.query(
            TeaLog.date, TeaLog.session, func.sum(TeaLog.count)
        ).filter(
            TeaLog.phone_number == user_id,
            func.extract("year", TeaLog.date) == today.year,
            func.extract("month", TeaLog.date) == today.month,
        ).group_by(TeaLog.date, TeaLog.session).order_by(TeaLog.date.asc()).all()
    finally:
        db.close()

    if not records:
        return "📊 No records found for this month."

    daily: dict[str, dict] = {}
    month_total = 0
    for r_date, r_sess, r_sub in records:
        r_sub = int(r_sub or 0)
        d = daily.setdefault(r_date.strftime("%d %b"), {"morning": 0, "evening": 0, "total": 0})
        d[r_sess] += r_sub
        d["total"] += r_sub
        month_total += r_sub

    lines = [f"📅 {today.strftime('%B')} Summary:"]
    for d_str, val in daily.items():
        lines.append(f"• {d_str}: {teas(val['total'])} (M:{val['morning']}, E:{val['evening']})")
    lines.append(f"Month Total: {teas(month_total)}.")
    if include_price:
        lines.append(_price_line(month_total))
    return "\n".join(lines)


# ---------- entry point ----------

def build_reply(user_id: str, user_name: str, text_body: str) -> str:
    """Apply all business rules and return the reply text.
    Synchronous (DB + Gemini) - call via asyncio.to_thread."""
    current = now()
    today = current.date()
    command = text_body.split()[0].split("@")[0].lower() if text_body.startswith("/") else None

    if command in ("/start", "/help"):
        return HELP_TEXT
    if command == "/total":
        return _summary(user_id, today)

    # --- pending duplicate confirmation ---
    with _pending_lock:
        pending = _pending.pop(user_id, None)
    if pending and pending.expires_at > current:
        answer = _normalize_reply(text_body)
        if answer in YES_WORDS:
            if active_slot(current) != pending.session or pending.day != today:
                return f"⏰ The {pending.session.capitalize()} slot has closed — nothing was recorded.\n{SLOT_TIMINGS_TEXT}"
            return _record(user_id, user_name, pending.session, pending.count, today)
        if answer in NO_WORDS:
            return "❌ Okay, nothing was recorded."
        # Any other message discards the pending request and is processed normally

    if command:
        return "❓ Unknown command. Type /help."

    parsed = local_parse(text_body) or parse_user_message(text_body)
    action = parsed["action"]

    if action == "error":
        return "⏳ I'm a bit busy right now. Please send that again in a minute."
    if action == "query":
        return _query(user_id, parsed, today)
    if action in ("confirm_yes", "confirm_no"):
        return "ℹ️ There's nothing waiting for confirmation."
    if action not in ("log", "cancel"):
        return REJECT_TEXT

    # --- strict time windows ---
    slot = active_slot(current)
    if slot is None:
        return _closed_text(action)
    requested = parsed["session"]
    if requested and requested != slot:
        return (
            f"⏰ The {requested.capitalize()} slot is not open now — only {slot.capitalize()} is active.\n"
            f"Valid slot timings:\n{SLOT_TIMINGS_TEXT}"
        )

    count = parsed["count"]
    if count is not None and count < 1:
        return "⚠️ Please send a valid number of teas, e.g. 'mrng 2 tea'."
    if count is not None and count > MAX_CUPS_PER_ENTRY:
        return f"⚠️ That's a lot of tea! Max {MAX_CUPS_PER_ENTRY} per entry."

    if action == "log":
        return _handle_log(user_id, user_name, slot, count or 1, current)
    return _handle_cancel(user_id, slot, count, today, bool(parsed.get("bulk_remove")))
