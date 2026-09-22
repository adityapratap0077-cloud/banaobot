"""Multi-tenancy tests for BanaoBot.

Verifies:
  1. Two businesses with different menus: booking/menu/FAQ in each returns
     ONLY that business's data (no cross-business leakage).
  2. Sessions are isolated per (business, phone).
  3. server.process_message scopes sessions/bookings/alerts to the business.
  4. Meta webhook payloads route by phone_number_id to the right business.

Usage: python3 test_platform.py
Exits non-zero on the first failure.
"""

import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import engine
import server
from storage import Store

TODAY = date(2026, 9, 23)
PASS = 0


def check(cond, label):
    global PASS
    if not cond:
        print(f"  FAIL: {label}")
        sys.exit(1)
    PASS += 1
    print(f"  ok: {label}")


def bodies(replies):
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


def make_dhaba(store):
    """Second business: Sharma Dhaba, with a tiny distinct menu + FAQ."""
    uid = store.create_user("owner@example.com", "hash")
    bid = store.create_business(
        uid, "Sharma Dhaba",
        tagline_en="Highway dhaba food", tagline_hi="ढाबे का खाना",
        hours_open="08:00", hours_close="22:00", last_booking="21:30",
        address_en="NH-27, Gorakhpur", address_hi="NH-27, गोरखपुर",
        owner_phone="+91 90000 00001",
        welcome_en="Welcome to *Sharma Dhaba*! Tap below 👇",
        welcome_hi="*शर्मा ढाबा* में स्वागत है! नीचे दबाएँ 👇",
        status="active",
    )
    cid = store.add_category(bid, "Snacks", "नाश्ता", "🍘")
    store.add_item(cid, "Masala Chai", "मसाला चाय", 20, 1, "kulhad chai")
    store.add_item(cid, "Chicken Curry", "चिकन करी", 250, 0, "")
    store.add_faq(bid, "chai", "chai, tea, चाय",
                  "Our kulhad chai is ₹20.", "हमारी कुल्हड़ चाय ₹20 की है।")
    return bid


# ------------------------------------------------- 1. engine isolation
print("(1) engine: no cross-business leakage")
store = Store(":memory:")
dhaba = make_dhaba(store)
bhoj = store.get_default_business_id()
biz_bhoj = store.get_business_bundle(bhoj)
biz_dhaba = store.get_business_bundle(dhaba)

phone = "919111111111"
r, _ = engine.handle_message(phone, "menu", None, biz_dhaba, today=TODAY)
ids = reply_ids(r)
# category list titles live in list rows; inspect row titles directly
titles = [row["title"] for rep in r if rep["type"] == "interactive"
          for s in rep["interactive"]["action"]["sections"] for row in s["rows"]]
check(any("Snacks" in t for t in titles), "dhaba menu lists Snacks")
check(not any("Starters" in t for t in titles), "dhaba menu hides Bhoj House cats")
check(not any("Main Course" in t for t in titles), "dhaba menu hides Main Course")

r, _ = engine.handle_message(phone, "menu", None, biz_bhoj, today=TODAY)
titles = [row["title"] for rep in r if rep["type"] == "interactive"
          for s in rep["interactive"]["action"]["sections"] for row in s["rows"]]
check(any("Starters" in t for t in titles), "bhoj menu still lists Starters")
check(not any("Snacks" in t for t in titles), "bhoj menu hides dhaba cats")

# items view isolation
cat_id = next(c["id"] for c in biz_dhaba["menu"] if c["name"]["en"] == "Snacks")
r, _ = engine.handle_message(phone, f"cmd:cat:{cat_id}", None, biz_dhaba,
                             today=TODAY)
txt = bodies(r)[0]
check("Masala Chai" in txt and "₹20" in txt, "dhaba items show chai ₹20")
check("Butter Chicken" not in txt, "dhaba items hide Bhoj House dishes")

# FAQ isolation
r, _ = engine.handle_message(phone, "do you serve chai?", None, biz_dhaba,
                             today=TODAY)
check("kulhad chai" in bodies(r)[0], "dhaba chai FAQ answered")
r, _ = engine.handle_message(phone, "do you serve chai?", None, biz_bhoj,
                             today=TODAY)
check("kulhad chai" not in bodies(r)[0], "bhoj does not answer dhaba FAQ")

# welcome / handoff use the right business identity
r, _ = engine.handle_message(phone, "hi", None, biz_dhaba, today=TODAY)
check("Sharma Dhaba" in bodies(r)[0], "welcome uses dhaba name")
check("Bhoj House" not in bodies(r)[0], "welcome hides Bhoj House")
r, _ = engine.handle_message(phone, "human", None, biz_dhaba, today=TODAY)
check("+91 90000 00001" in bodies(r)[0], "handoff shows dhaba owner phone")

# booking hours come from the business (dhaba opens 08:00, last 21:30)
sess = None
for msg in ["cmd:book", "tomorrow", "7am"]:
    r, sess = engine.handle_message(phone, msg, sess, biz_dhaba, today=TODAY)
check(sess["state"] == "book_time", "7am rejected for dhaba (opens 08:00)")
r, sess = engine.handle_message(phone, "9am", sess, biz_dhaba, today=TODAY)
check(sess["state"] == "book_size", "9am accepted for dhaba")

# ------------------------------------------------- 2. session isolation
print("(2) sessions isolated per (business, phone)")
store2 = Store(":memory:")
dhaba2 = make_dhaba(store2)
bhoj2 = store2.get_default_business_id()
store2.save_session(phone, {"lang": "hi", "state": "menu_cat", "data": {}},
                    business_id=dhaba2)
s_dhaba = store2.get_session(phone, business_id=dhaba2)
s_bhoj = store2.get_session(phone, business_id=bhoj2)
check(s_dhaba["lang"] == "hi" and s_dhaba["state"] == "menu_cat",
      "dhaba session stored")
check(s_bhoj is None, "same phone has no session under bhoj")

# ------------------------------------------------- 3. pipeline scoping
print("(3) server.process_message scopes everything to the business")
server.store = store
server.app.config["store"] = store
replies, resolved = server.process_message("919222222222", "hi", business_id=dhaba)
check(resolved == dhaba, "process_message resolves explicit business_id")
check("Sharma Dhaba" in bodies(replies)[0], "reply carries dhaba identity")

# full booking through the pipeline -> scoped booking + scoped session
ph = "919333333333"
for msg in ["cmd:book", "tomorrow", "8pm", "2", "Ravi", "9876501234",
            "cmd:confirm_booking"]:
    replies, _ = server.process_message(ph, msg, business_id=dhaba)
bid_saved = store.list_bookings(dhaba)[0]["id"]
check(bid_saved.startswith("SD-"), f"dhaba booking id prefix SD- ({bid_saved})")
check(store.count_bookings(dhaba) == 1, "booking counted under dhaba")
check(store.count_bookings(bhoj) == 0, "no booking leaked to bhoj")
check(bodies(replies)[0].count(bid_saved) >= 1, "confirmation echoes booking id")
sess = store.get_session(ph, business_id=dhaba)
check(sess["state"] == "idle", "session back to idle under dhaba")

# handoff alert scoped
server.process_message("919444444444", "human", business_id=dhaba)
check(len(store.list_alerts(dhaba)) == 1, "alert stored under dhaba")
check(len(store.list_alerts(bhoj)) == 0, "no alert leaked to bhoj")

# message log scoped
check(store.count_messages(dhaba, "in") >= 8, "inbound messages logged for dhaba")

# ------------------------------------------------- 4. webhook routing
print("(4) webhook routes by phone_number_id")
store.set_whatsapp_credentials(dhaba, "pnid_dhaba_123", "tok")
store.set_whatsapp_credentials(bhoj, "pnid_bhoj_456", "tok")


def webhook_payload(pnid, phone, text):
    return {"entry": [{"changes": [{"value": {
        "metadata": {"phone_number_id": pnid},
        "messages": [{"from": phone, "id": "wamid.1",
                      "text": {"body": text}}]}}]}]}


client = server.app.test_client()
resp = client.post("/webhook", json=webhook_payload("pnid_dhaba_123",
                                                   "919555555555", "hi"))
check(resp.status_code == 200, "webhook 200 for mapped pnid")
check(store.count_messages(dhaba, "in") >= 9, "mapped pnid routed to dhaba")

resp = client.post("/webhook", json=webhook_payload("pnid_unknown_xyz",
                                                   "919666666666", "hi"))
check(resp.status_code == 200, "webhook 200 for unmapped pnid")
check(store.get_session("919666666666",
                        business_id=bhoj) is not None,
      "DEMO_MODE: unmapped pnid falls back to demo business")

# button_reply payloads route too
payload = {"entry": [{"changes": [{"value": {
    "metadata": {"phone_number_id": "pnid_bhoj_456"},
    "messages": [{"from": "919777777777", "id": "wamid.2",
                  "interactive": {"type": "button_reply",
                                  "button_reply": {"id": "cmd:menu"}}}]}}]}]}
resp = client.post("/webhook", json=payload)
check(resp.status_code == 200, "webhook 200 for button_reply")
sess = store.get_session("919777777777", business_id=bhoj)
check(sess is not None and sess["state"] == "menu_cat",
      "button tap routed to bhoj session")

# /demo/message honours business_id, 404s on unknown
resp = client.post("/demo/message",
                   json={"phone": "919888888888", "text": "menu",
                         "business_id": dhaba})
check(resp.status_code == 200, "/demo/message 200 with business_id")
data = resp.get_json()
check(data["business_id"] == dhaba, "response echoes business_id")
resp = client.post("/demo/message",
                   json={"phone": "x", "text": "hi", "business_id": 999999})
check(resp.status_code == 404, "/demo/message 404 on unknown business")

print(f"\nALL {PASS} PLATFORM CHECKS PASSED ✔")
