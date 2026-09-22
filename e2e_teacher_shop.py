"""E2E: dashboard onboarding -> /demo/message for a teacher and a shop.

Exercises the real HTTP routes: signup, template picker, basics POST,
catalog JSON API, then WhatsApp-style chats via /demo/message.
Writes to a temp SQLite file (the app's DEMO_MODE store path is patched).

Usage: python3 e2e_teacher_shop.py
"""

import json
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
tmp.close()
os.environ["BANAOBOT_DB"] = tmp.name
os.environ["BANAOBOT_SECRET"] = "e2e-test-secret"
os.environ["DEMO_MODE"] = "1"

import server

PASS = 0


def check(cond, label):
    global PASS
    if not cond:
        print(f"  FAIL: {label}")
        sys.exit(1)
    PASS += 1
    print(f"  ok: {label}")


def reply_texts(replies):
    out = []
    for r in replies:
        if r["type"] == "text":
            out.append(r["text"]["body"])
        elif r["type"] == "interactive":
            iv = r["interactive"]
            out.append(iv["body"]["text"])
            if iv["type"] == "list":
                for sec in iv["action"]["sections"]:
                    out.append(sec["title"])
                    for row in sec["rows"]:
                        out.append(row["title"] + " " + (row.get("description") or ""))
    return out


def btn_titles(replies):
    out = []
    for r in replies:
        if r["type"] == "interactive" and r["interactive"]["type"] == "button":
            out += [b["reply"]["title"] for b in r["interactive"]["action"]["buttons"]]
    return out


client = server.app.test_client()

# ---- signup ---------------------------------------------------------------
r = client.post("/app/signup", data={
    "email": "e2e@example.com", "password": "secret123", "confirm": "secret123",
    "name": "E2E"}, follow_redirects=False)
check(r.status_code in (302, 303), "signup redirects")
print("  signed up as e2e@example.com")

# ---- step 0: template picker ----------------------------------------------
r = client.get("/app/onboarding")
check(r.status_code == 200, "picker page loads")
html = r.get_data(as_text=True)
for name in ["Restaurant", "Shop", "Freelancer", "Clinic", "Teacher", "Creator"]:
    check(name in html, f"picker shows {name} card")

# ---- teacher onboarding ---------------------------------------------------
print("== Adiroxx Guitar Classes (teacher) ==")
r = client.get("/app/onboarding/basics?template=teacher")
check(r.status_code == 200, "teacher basics page loads")
check("courses" in r.get_data(as_text=True).lower(), "basics page is teacher-aware")
r = client.post("/app/onboarding/basics", data={
    "template": "teacher", "name": "Adiroxx Guitar Classes",
    "language": "en", "owner_phone": "919876543210",
    "tagline_en": "Learn guitar the fun way"}, follow_redirects=False)
check(r.status_code in (302, 303), "teacher basics POST redirects")
bid_t = int(re.search(r"/app/onboarding/(\d+)/menu", r.headers["Location"]).group(1))
check(bid_t > 0, f"teacher business created (id={bid_t})")

# build courses catalog via the JSON API
r = client.post(f"/app/api/business/{bid_t}/categories",
                json={"name_en": "Guitar Courses", "name_hi": "गिटार कोर्स",
                      "emoji": "🎸"})
cat = r.get_json()["id"]
check(r.get_json()["ok"], "category created")
for name, price in [("Beginner Guitar", 499), ("Fingerstyle Mastery", 999)]:
    r = client.post(f"/app/api/categories/{cat}/items",
                    json={"name_en": name, "price": price, "veg": 1})
    check(r.get_json()["ok"], f"course added: {name}")

# ---- teacher WhatsApp chat via /demo/message ------------------------------
def chat(bid, phone, text):
    r = client.post("/demo/message",
                    json={"phone": phone, "text": text, "business_id": bid})
    check(r.status_code == 200, f"/demo/message ok for {text!r}")
    return r.get_json()["replies"]

replies = chat(bid_t, "919110000001", "hi")
body = reply_texts(replies)[0]
titles = btn_titles(replies)
check("Adiroxx Guitar Classes" in body, "teacher greeting names the business")
check("🎓 View Courses" in titles, "teacher catalog button")
check("🎓 Book Free Demo" in titles, "teacher action button")
check(all(len(t) <= 20 for t in titles), "teacher buttons <= 20 chars")

replies = chat(bid_t, "919110000001", "cmd:menu")
texts = " ".join(reply_texts(replies))
check("Guitar Courses" in texts, "courses browsable")
replies = chat(bid_t, "919110000001", f"cmd:cat:{cat}")
check("Beginner Guitar" in reply_texts(replies)[0], "course item listed with price")

replies = chat(bid_t, "919110000002", "hi")
replies = chat(bid_t, "919110000002", "cmd:book")
replies = chat(bid_t, "919110000002", "tomorrow")
replies = chat(bid_t, "919110000002", "4pm")
check("students" in reply_texts(replies)[0].lower(), "demo booking asks for students")
replies = chat(bid_t, "919110000002", "2")
replies = chat(bid_t, "919110000002", "Aarav")
replies = chat(bid_t, "919110000002", "9876543210")
check("students" in reply_texts(replies)[0].lower(), "teacher summary uses students")
replies = chat(bid_t, "919110000002", "cmd:confirm_booking")
body = reply_texts(replies)[0]
check("Aarav" in body, "confirmation uses the student's name")
print("  teacher booking confirmed:", body.split("\n")[0][:80])

# ---- shop onboarding ------------------------------------------------------
print("== Sharma General Store (shop) ==")
r = client.post("/app/onboarding/basics", data={
    "template": "shop", "name": "Sharma General Store",
    "language": "en", "owner_phone": "919876543211"}, follow_redirects=False)
bid_s = int(re.search(r"/app/onboarding/(\d+)/menu", r.headers["Location"]).group(1))
check(bid_s > 0 and bid_s != bid_t, f"shop business created (id={bid_s})")

r = client.post(f"/app/api/business/{bid_s}/categories",
                json={"name_en": "Daily Needs", "emoji": "🛒"})
cat_s = r.get_json()["id"]
check(r.get_json()["ok"], "category created")
for name, price in [("Blue Shirt", 499), ("Jeans", 999)]:
    r = client.post(f"/app/api/categories/{cat_s}/items",
                    json={"name_en": name, "price": price, "veg": 1})
    check(r.get_json()["ok"], f"product added: {name}")

replies = chat(bid_s, "919110000003", "hi")
titles = btn_titles(replies)
check("🛍 Browse Products" in titles, "shop catalog button")
check("🛒 Enquire to Order" in titles, "shop action button")
check("cmd:book" not in json.dumps(replies), "shop has no book flow")

replies = chat(bid_s, "919110000003", "i want to order")
check("book_date" not in json.dumps(replies), "order never enters date/time booking")
replies = chat(bid_s, "919110000003", "2x Blue Shirt")
replies = chat(bid_s, "919110000003", "Rahul")
replies = chat(bid_s, "919110000003", "9876543210")
replies = chat(bid_s, "919110000003", "cmd:confirm_enquiry")
check("Rahul" in reply_texts(replies)[0], "enquiry confirmation names the customer")

# owner alert persisted, no booking row
store = server.store
alerts = store.list_alerts(bid_s)
check(any("New order enquiry" in a["reason"] and "Blue Shirt" in a["reason"]
          for a in alerts), "shop owner alert persisted with items")
check(store.count_bookings(bid_s) == 0, "shop enquiry created no booking")
check(store.count_bookings(bid_t) == 1, "teacher booking stored, shop untouched")
t_alerts = store.list_alerts(bid_t)
check(all("Blue Shirt" not in a["reason"] for a in t_alerts),
      "shop alert not visible to teacher")

# ---- business home is template-aware --------------------------------------
r = client.get(f"/app/business/{bid_t}")
html = r.get_data(as_text=True)
check("Teacher" in html and "students" in html.lower(), "teacher home shows template + unit")
r = client.get(f"/app/business/{bid_s}")
check("Shop" in r.get_data(as_text=True), "shop home shows template badge")

# ---- settings: tone override ----------------------------------------------
r = client.post(f"/app/business/{bid_t}/settings",
                data={"name": "Adiroxx Guitar Classes", "tone": "casual",
                      "booking_enabled": "1", "language": "en",
                      "owner_phone": "919876543210"},
                follow_redirects=False)
check(r.status_code in (302, 303), "settings saved")
bundle = store.get_business_bundle(bid_t)
check(bundle["tone"] == "casual", "tone override persisted (friendly -> casual)")
replies = chat(bid_t, "919110000099", "blargzz")
print("  casual fallback sample:", reply_texts(replies)[0].split("\n")[0][:90])

print(f"\nALL {PASS} E2E CHECKS PASSED ✔")
print(f"(temp db at {tmp.name} — delete to sanitize)")
