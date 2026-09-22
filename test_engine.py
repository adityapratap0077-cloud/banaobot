"""Scripted end-to-end tests for the Bhoj House bot.

Runs full conversations through engine + storage (in-memory SQLite),
exactly like server.process_message does. Covers:
  (a) full booking flow to confirmation
  (b) menu browse with back navigation
  (c) an FAQ asked in Hindi
  (d) gibberish -> fallback -> human handoff
  (e) booking cancellation (no booking saved)
  (f) language switching + English FAQ sanity

Usage: python3 test_engine.py
Exits non-zero on the first failure.
"""

import os
import sys
import tempfile
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import engine
from storage import Store

TODAY = date(2026, 9, 23)  # fixed "today" so date tests are deterministic
PASS = 0


def check(cond, label):
    global PASS
    if not cond:
        print(f"  FAIL: {label}")
        sys.exit(1)
    PASS += 1
    print(f"  ok: {label}")


def make_client(tag):
    """Fresh in-memory store + a send() helper bound to one phone number."""
    store = Store(":memory:")
    phone = f"9190000000{tag:02d}"

    def send(text):
        session = store.get_session(phone)
        replies, new_session = engine.handle_message(phone, text, session, today=TODAY)
        events = new_session.pop("_events", [])
        for ev in events:
            if ev["type"] == "save_booking":
                store.save_booking(ev["booking"])
            elif ev["type"] == "owner_alert":
                store.add_alert(phone, ev["reason"])
        store.save_session(phone, new_session)
        return replies, new_session, events

    return send, store


def bodies(replies):
    """Extract visible text from replies (text bodies + interactive bodies)."""
    out = []
    for r in replies:
        if r["type"] == "text":
            out.append(r["text"]["body"])
        elif r["type"] == "interactive":
            out.append(r["interactive"]["body"]["text"])
    return out


def reply_ids(replies):
    ids = []
    for r in replies:
        if r["type"] == "interactive":
            iv = r["interactive"]
            if iv["type"] == "button":
                ids += [b["reply"]["id"] for b in iv["action"]["buttons"]]
            elif iv["type"] == "list":
                for s in iv["action"]["sections"]:
                    ids += [row["id"] for row in s["rows"]]
    return ids


# ---------------------------------------------------------------- (a) booking
print("(a) full booking flow to confirmation")
send, store = make_client(1)
r, s, _ = send("hi")
check("cmd:book" in reply_ids(r), "greeting shows Book button")
r, s, _ = send("cmd:book")
check(s["state"] == "book_date", "booking started -> asks date")
r, s, _ = send("tomorrow")
check(s["state"] == "book_time" and s["data"]["booking"]["date"] == "2026-09-24",
      "date 'tomorrow' parsed to 2026-09-24")
r, s, _ = send("8pm")
check(s["data"]["booking"]["time"] == "20:00", "time '8pm' -> 20:00")
r, s, _ = send("4")
check(s["data"]["booking"]["party_size"] == 4, "party size 4")
r, s, _ = send("Aditya")
check(s["data"]["booking"]["name"] == "Aditya", "name captured")
r, s, _ = send("9876543210")
check(s["state"] == "book_confirm", "valid phone -> confirmation step")
check("cmd:confirm_booking" in reply_ids(r), "confirmation has Confirm button")
summary = bodies(r)[0]
check("2026-09-24" not in summary and "24 Sep" in summary or "Sep" in summary,
      "summary shows readable date")
r, s, ev = send("cmd:confirm_booking")
check(s["state"] == "idle", "back to idle after confirm")
check(len(ev) == 1 and ev[0]["type"] == "save_booking", "save_booking event emitted")
check(ev[0]["booking"]["id"].startswith("BH-"), "booking id like BH-XXXXXX")
check(store.count_bookings() == 1, "booking persisted in sqlite")
msg = bodies(r)[0]
check(ev[0]["booking"]["id"] in msg, "confirmation message contains booking id")

# ------------------------------------------------------- (b) menu navigation
print("(b) menu browse with back navigation")
send, store = make_client(2)
send("hi")
r, s, _ = send("cmd:menu")
check(s["state"] == "menu_cat", "menu -> category list")
check("cmd:cat:mains" in reply_ids(r), "category list has Main Course")
r, s, _ = send("cmd:cat:mains")
check(s["state"] == "menu_items", "category -> items view")
items_text = bodies(r)[0]
check("Butter Chicken" in items_text and "₹320" in items_text,
      "items show names + ₹ prices")
check("cmd:menu" in reply_ids(r), "items view has Back button")
r, s, _ = send("cmd:menu")
check(s["state"] == "menu_cat", "Back returns to categories")
r, s, _ = send("starters")  # natural text also works
check(s["state"] == "menu_items" and "Paneer Tikka" in bodies(r)[0],
      "typed category name works too")

# ---------------------------------------------------------------- (c) Hindi FAQ
print("(c) FAQ in Hindi")
send, store = make_client(3)
r, s, _ = send("नमस्ते")
check(s["lang"] == "hi", "Devanagari greeting auto-detects Hindi")
check("भोज हाउस" in bodies(r)[0], "welcome reply is in Hindi")
r, s, _ = send("क्या होम डिलीवरी होती है?")
ans = bodies(r)[0]
check("होम डिलीवरी" in ans and "Zomato" in ans, "Hindi delivery FAQ answered")
r, s, _ = send("/english")
check(s["lang"] == "en", "/english switches language")
r, s, _ = send("do you have parking?")
check("Parking" in bodies(r)[0], "English FAQ still works after switch")

# ------------------------------------------------- (d) fallback -> handoff
print("(d) gibberish -> fallback -> human handoff")
send, store = make_client(4)
send("hi")
r, s, _ = send("xyzqwe blarg")
check("didn't quite get that" in bodies(r)[0], "gibberish -> fallback message")
check("cmd:human" in reply_ids(r), "fallback offers Talk to Human")
r, s, ev = send("mujhe kisi insaan se baat karni hai")
check(len(ev) == 1 and ev[0]["type"] == "owner_alert", "owner_alert event emitted")
check("Connecting you to our team" in bodies(r)[0], "handoff message shown")
check(len(store.list_alerts()) == 1, "alert persisted in sqlite")

# ------------------------------------------------------ (e) cancellation
print("(e) booking cancellation saves nothing")
send, store = make_client(5)
send("hi")
send("cmd:book")
send("today")
send("7:30pm")
send("2")
send("Test User")
r, s, _ = send("9123456789")
check(s["state"] == "book_confirm", "reached confirm step")
r, s, ev = send("cmd:cancel_booking")
check(s["state"] == "idle", "cancel -> idle")
check(ev == [], "no events on cancel")
check(store.count_bookings() == 0, "no booking saved after cancel")
check("cancelled" in bodies(r)[0].lower(), "cancellation acknowledged")
# mid-flow typed cancel
send("cmd:book")
r, s, _ = send("cancel")
check(s["state"] == "idle", "typed 'cancel' mid-flow aborts booking")

# ------------------------------------------------- (f) validation edge cases
print("(f) input validation")
send, store = make_client(6)
send("cmd:book")
r, s, _ = send("32-13-2026")
check(s["state"] == "book_date", "impossible date rejected, stays on date step")
r, s, _ = send("tomorrow")
r, s, _ = send("3am")
check(s["state"] == "book_time", "3am rejected (outside hours)")
r, s, _ = send("25:00")
check(s["state"] == "book_time", "25:00 rejected")
r, s, _ = send("19:30")
r, s, ev = send("99")
check(s["state"] == "idle", "99 guests -> owner-confirm handoff, back to idle")
check(len(ev) == 1 and ev[0]["type"] == "owner_alert",
      "owner_alert raised for 99 guests")
check("owner" in bodies(r)[0].lower(), "polite over-capacity message shown")
check(store.count_bookings() == 0, "no booking saved for over-capacity")
# fresh booking for the remaining validation checks
send("cmd:book")
send("tomorrow")
send("19:30")
r, s, _ = send("2")
r, s, _ = send("X")
check(s["state"] == "book_name", "1-char name rejected")
r, s, _ = send("Ravi Kumar")
r, s, _ = send("12345")
check(s["state"] == "book_phone", "short number rejected")
r, s, _ = send("+91 98765 43210")
check(s["state"] == "book_confirm", "+91 number with spaces accepted")

# ------------------------------------------------- (g) date+time in one message
print("(g) 'tomorrow 9pm' skips the time question")
send, store = make_client(7)
send("hi")
send("cmd:book")
r, s, _ = send("tomorrow 9pm")
check(s["state"] == "book_size", "combo message jumps straight to party size")
check(s["data"]["booking"]["date"] == "2026-09-24", "date captured from combo")
check(s["data"]["booking"]["time"] == "21:00", "time captured from combo")
r, s, _ = send("4")
check(s["data"]["booking"]["party_size"] == 4, "flow continues to name step")

# ------------------------------------------------- (h) time first, then date
print("(h) '8pm' first, date after")
send, store = make_client(8)
send("hi")
send("cmd:book")
r, s, _ = send("8pm")
check(s["state"] == "book_time" and s["data"]["booking"].get("time") == "20:00",
      "time stashed, date still asked")
r, s, _ = send("tomorrow")
check(s["state"] == "book_size", "date after time -> party size step")
check(s["data"]["booking"]["date"] == "2026-09-24", "date captured")

# ------------------------------------------------- (i) vague large group
print("(i) 'a lot of people' -> owner confirm, no loop")
send, store = make_client(9)
send("hi")
send("cmd:book")
send("tomorrow")
send("8pm")
r, s, ev = send("a lot of people")
check(s["state"] == "idle", "vague large group -> handoff, back to idle")
check(len(ev) == 1 and ev[0]["type"] == "owner_alert", "owner_alert raised")
check("25" not in bodies(r)[0], "no interrogation loop")

print(f"\nALL {PASS} CHECKS PASSED ✔")
