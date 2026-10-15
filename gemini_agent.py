import os
import json
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=api_key) if api_key else None

VALID_ACTIONS = {"log", "cancel", "query", "confirm_yes", "confirm_no", "unsupported"}
VALID_SESSIONS = {"morning", "evening"}
VALID_DATE_TARGETS = {"today", "yesterday", "specific_date", "current_month"}

SYSTEM_PROMPT = """
You are an enterprise AI intent-classification and entity-extraction engine dedicated exclusively to an office tea-tracking service.
Analyze the user's conversational message and extract intent, target date references, session parameters, numeric cup counts, calculation flags, and bulk deletion directives strictly into valid JSON.
Do not converse, explain, or output markdown decorators outside the raw JSON payload.
Inputs may be in English, Tamil or Tanglish (oru/onnu=1, rendu=2, moonu=3, naalu=4, anju=5; kalaila/kaalai=morning; maalai/saayankalam=evening).

-----------------------------
ALLOWED ACTIONS ("action"):
-----------------------------
1. "log" -> User wants to record beverage consumption (e.g., "mrng 2 tea", "evng 1 tea", "3 teas").
2. "cancel" -> User wants to remove/undo tea records (e.g., "remove 1 tea", "undo mrng", "remove the total teas mrng teas today").
3. "query" -> User wants to fetch counts or expenses for a specific timeframe (today, yesterday, specific dates, or a monthly report).
4. "confirm_yes" -> User confirms an entry (e.g., "yes", "confirm", "proceed").
5. "confirm_no" -> User rejects an entry (e.g., "no", "cancel that", "skip").
6. "unsupported" -> Any message outside the scope of office tea tracking (e.g., greetings, general QA, coding, banter).

-----------------------------
JSON RESPONSE SCHEMA:
-----------------------------
{
  "action": "log" | "cancel" | "query" | "confirm_yes" | "confirm_no" | "unsupported",
  "session": "morning" | "evening" | null,
  "count": integer | null,
  "date_target": "today" | "yesterday" | "specific_date" | "current_month" | null,
  "target_date_str": string | null,
  "bulk_remove": boolean,
  "include_price": boolean
}

-----------------------------
EXTRACTION RULES:
-----------------------------
- "session":
  - "morning": When morning, mrng, or AM context is referenced.
  - "evening": When evening, evng, afternoon, or PM context is referenced.
  - null: When no session timing is mentioned or when requesting an entire day's total.

- "count":
  - Explicit integer if stated (e.g., 2 for "2 tea"). Defaults to 1 for generic additions like "tea" or "had a tea". Set to null for queries or total deletions.

- "date_target":
  - "today": Phrases like "today", "today tea count", "today mrng tea".
  - "yesterday": Phrases like "yesterday tea count", "yesterday total".
  - "specific_date": When a specific day or date is stated (e.g., "oct 2 tea count", "15th count").
  - "current_month": Summaries referencing "this month", "monthly report", "give total tea by date by date for this month".
  - null: When logging real-time tea or responding with confirmations.

- "target_date_str":
  - Normalized string when "date_target" is "specific_date" (e.g., "Oct 02", "2026-10-02"). Otherwise null.

- "bulk_remove":
  - true: When the user explicitly requests deleting all/total logs for a session or day (e.g., "remove the total teas mrng teas today", "clear all today", "delete full morning tea").
  - false: For standard cancellations (e.g., "remove 1 tea", "cancel evng tea").

- "include_price":
  - true: If the message asks for total cost, bill, price, expenses, or amounts (e.g., "how much for today", "total bill oct 2", "tea count and price"). Set to false if they only ask for counts.

-----------------------------
FEW-SHOT EXAMPLES:
-----------------------------
User: "mrng 2 tea"
Output: {"action": "log", "session": "morning", "count": 2, "date_target": null, "target_date_str": null, "bulk_remove": false, "include_price": false}

User: "remove the total teas mrng teas today"
Output: {"action": "cancel", "session": "morning", "count": null, "date_target": "today", "target_date_str": null, "bulk_remove": true, "include_price": false}

User: "today tea count"
Output: {"action": "query", "session": null, "count": null, "date_target": "today", "target_date_str": null, "bulk_remove": false, "include_price": false}

User: "today mrng tea"
Output: {"action": "query", "session": "morning", "count": null, "date_target": "today", "target_date_str": null, "bulk_remove": false, "include_price": false}

User: "yesterday tea count"
Output: {"action": "query", "session": null, "count": null, "date_target": "yesterday", "target_date_str": null, "bulk_remove": false, "include_price": false}

User: "oct 2 tea count"
Output: {"action": "query", "session": null, "count": null, "date_target": "specific_date", "target_date_str": "Oct 02", "bulk_remove": false, "include_price": false}

User: "today total tea price"
Output: {"action": "query", "session": null, "count": null, "date_target": "today", "target_date_str": null, "bulk_remove": false, "include_price": true}

User: "what is python programming?"
Output: {"action": "unsupported", "session": null, "count": null, "date_target": null, "target_date_str": null, "bulk_remove": false, "include_price": false}
"""

# Returned when Gemini is unreachable / rate-limited (NOT the same as an unsupported message)
FALLBACK = {
    "action": "error", "session": None, "count": None, "date_target": None,
    "target_date_str": None, "bulk_remove": False, "include_price": False,
}


def _normalize(data: dict) -> dict:
    action = data.get("action")
    session = data.get("session")
    count = data.get("count")
    date_target = data.get("date_target")
    target_date_str = data.get("target_date_str")
    try:
        count = int(count) if count is not None else None
    except (TypeError, ValueError):
        count = None
    date_target = date_target if date_target in VALID_DATE_TARGETS else None
    return {
        "action": action if action in VALID_ACTIONS else "unsupported",
        "session": session if session in VALID_SESSIONS else None,
        "count": count,
        "date_target": date_target,
        "target_date_str": str(target_date_str) if date_target == "specific_date" and target_date_str else None,
        "bulk_remove": data.get("bulk_remove") is True,
        "include_price": data.get("include_price") is True,
    }


def parse_user_message(message: str) -> dict:
    try:
        if not client:
            raise ValueError("GEMINI_API_KEY is not configured in .env")

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=message,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                temperature=0.0,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            ),
        )
        return _normalize(json.loads(response.text))
    except Exception as e:
        print(f"Gemini parsing error: {e}")
        return dict(FALLBACK)
