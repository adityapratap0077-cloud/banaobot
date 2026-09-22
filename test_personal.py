"""Tests for the Personal Chatbot template (no business / no Meta required).

Covers:
  (a) template picker lists Personal Chatbot
  (b) personal onboarding works WITHOUT an owner phone
  (c) non-personal onboarding still requires the owner phone
  (d) personal bot has no booking flow (action button -> enquiry, not dates)
  (e) leave-a-message completes -> owner_alert event for the dashboard
  (f) zero-priced links never show "₹0"
  (g) personal connect page shows no Meta/Facebook form

Usage: python3 test_personal.py
Exits non-zero on the first failure.
"""

import os
import re
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("DEMO_MODE", "true")

import engine
import server
import templates
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


def fresh_client():
    store = Store(":memory:")
    server.store = store
    server.app.config["store"] = store
    return server.app.test_client(), store


def bodies(replies):
    out = []
    for r in replies:
        if r["type"] == "text":
            out.append(r["text"]["body"])
        elif r["type"] == "interactive":
            out.append(r["interactive"]["body"]["text"])
    return out


client, store = fresh_client()

# ------------------------------------------------- signup
print("(a) template picker lists Personal Chatbot")
r = client.post("/app/signup", data={
    "email": "me@test.local", "password": "secret123", "confirm": "secret123"})
check(r.status_code in (301, 302), "signup redirects")
r = client.get("/app/onboarding")
check(r.status_code == 200, "onboarding picker renders")
check(b"Personal Chatbot" in r.data, "Personal Chatbot listed in picker")
check(b'value="personal"' in r.data or b"personal" in r.data,
      "personal template value present")
check("personal" in templates.ids(), "personal registered in template ids")

# ------------------------------------------------- personal onboarding, no phone
print("(b) personal onboarding without owner phone")
r = client.post("/app/onboarding/basics?template=personal", data={
    "name": "Aditya Bot", "language": "en", "owner_phone": "",
    "tagline_en": "Music, tech, vibes"})
check(r.status_code in (301, 302), "personal onboarding POST redirects (no phone needed)")
m = re.search(r"/(\d+)/", r.headers["Location"])
pbid = int(m.group(1))
pbiz = store.get_business(pbid)
check(pbiz["template_id"] == "personal", "business created with personal template")
check(pbiz["owner_phone"] == "", "owner phone optional for personal")

# ------------------------------------------------- business onboarding still needs phone
print("(c) non-personal onboarding still requires owner phone")
r = client.post("/app/onboarding/basics?template=restaurant", data={
    "name": "No Phone Dhaba", "language": "en", "owner_phone": ""})
check(r.status_code == 200 and b"Owner phone is required" in r.data,
      "restaurant without phone -> error, not created")

# ------------------------------------------------- engine: personal bundle
print("(d) personal bot has no booking flow")
bundle = store.get_business_bundle(pbid)
check(engine._booking_on(bundle) is False,
      "personal bundle resolves booking OFF via template")
tpl = templates.get("personal")
check(tpl["booking_enabled"] is False, "personal template disables booking")
session = {"lang": "en", "state": "idle", "data": {}}
replies, session = engine.handle_message(
    "919000000201", "cmd:book", session, business=bundle, today=TODAY)
check(session["state"] == "enq_items",
      "action button starts enquiry (message flow), not booking dates")
txt = " ".join(bodies(replies)).lower()
check("date" not in txt and "time" not in txt,
      "no date/time questions in personal flow")

# ------------------------------------------------- leave a message -> owner alert
print("(e) leave-a-message raises a dashboard alert")
replies, session = engine.handle_message(
    "919000000201", "Hi Aditya, loved your track!", session,
    business=bundle, today=TODAY)
replies, session = engine.handle_message(
    "919000000201", "Rohan", session, business=bundle, today=TODAY)
replies, session = engine.handle_message(
    "919000000201", "9876543210", session, business=bundle, today=TODAY)
check(session["state"] == "enq_confirm", "phone accepted -> confirm step")
replies, session = engine.handle_message(
    "919000000201", "cmd:confirm_enquiry", session, business=bundle, today=TODAY)
events = session.pop("_events", [])
check(any(e["type"] == "owner_alert" for e in events),
      "completed message -> owner_alert event")
alert = next(e for e in events if e["type"] == "owner_alert")
check("Rohan" in alert["reason"], "alert carries the visitor's name")
store.add_alert("919000000201", alert["reason"], pbid)
alerts = store.list_alerts(pbid)
check(len(alerts) == 1, "alert lands on the personal dashboard")

# ------------------------------------------------- zero-priced links
print("(f) zero-priced links never show ₹0")
cat = store.add_category(pbid, "Socials", emoji="🔗")
store.add_item(cat, "Instagram", price=0)
bundle = store.get_business_bundle(pbid)
session = {"lang": "en", "state": "idle", "data": {}}
replies, session = engine.handle_message(
    "919000000202", "cmd:menu", session, business=bundle, today=TODAY)
replies, session = engine.handle_message(
    "919000000202", "socials", session, business=bundle, today=TODAY)
txt = " ".join(bodies(replies))
check("Instagram" in txt, "link listed")
check("₹0" not in txt, "no ₹0 shown for free links")

# ------------------------------------------------- personal connect page
print("(g) personal connect page has no Meta form")
r = client.get(f"/app/business/{pbid}/connect")
check(r.status_code == 200, "personal connect page renders")
check(b"Where your bot lives" in r.data, "personal connect headline shown")
check(b"Connect with Facebook" not in r.data,
      "no Facebook/Meta connect form for personal bots")
check(b"whatsapp_token" not in r.data.lower(),
      "no token form fields for personal bots")

print(f"\n{PASS} personal checks passed.")
