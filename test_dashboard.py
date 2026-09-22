"""HTTP integration tests for the BanaoBot dashboard (/app/*).

Covers the full owner self-test journey:
  signup -> login -> onboarding wizard (5 steps) -> menu builder API ->
  preview page -> simulated WhatsApp connect -> per-business isolation.

Usage: python3 test_dashboard.py
Exits non-zero on the first failure. Requires dashboard.py + templates/.
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("DEMO_MODE", "true")

import server
from storage import Store

PASS = 0


def check(cond, label):
    global PASS
    if not cond:
        print(f"  FAIL: {label}")
        sys.exit(1)
    PASS += 1
    print(f"  ok: {label}")


def fresh_client():
    """Rebind server to a fresh in-memory DB and return a test client."""
    store = Store(":memory:")
    server.store = store
    server.app.config["store"] = store
    return server.app.test_client(), store


def bid_from_location(loc):
    m = re.search(r"/(\d+)/", loc)
    assert m, f"no business id in redirect: {loc}"
    return int(m.group(1))


client, store = fresh_client()

# ------------------------------------------------- auth gating
print("(a) auth")
r = client.get("/app/")
check(r.status_code in (301, 302), "anonymous /app/ redirects to login")
r = client.get("/app/signup")
check(r.status_code == 200, "GET /app/signup renders")

# ------------------------------------------------- signup + login
print("(b) signup -> dashboard")
r = client.post("/app/signup", data={
    "email": "owner@test.local", "password": "secret123", "confirm": "secret123",
})
check(r.status_code in (301, 302), "signup redirects")
check("/app/" in r.headers["Location"], "signup lands on dashboard")
r = client.get("/app/")
check(r.status_code == 200 and b"New business" in r.data,
      "dashboard renders with New business button")

# duplicate email rejected (fresh client, not logged in)
c0 = server.app.test_client()
r = c0.post("/app/signup", data={
    "email": "owner@test.local", "password": "secret123", "confirm": "secret123"})
check(r.status_code == 200 and b"already registered" in r.data,
      "duplicate signup shows friendly error")

# logout -> login
client.get("/app/logout")
r = client.get("/app/")
check(r.status_code in (301, 302), "logged out: /app/ redirects again")
r = client.post("/app/login", data={
    "email": "owner@test.local", "password": "secret123"})
check(r.status_code in (301, 302), "login redirects to dashboard")
c1 = server.app.test_client()
r = c1.post("/app/login", data={
    "email": "owner@test.local", "password": "wrong"})
check(r.status_code == 200 and b"Invalid email or password" in r.data,
      "wrong password shows error")
client.post("/app/login", data={
    "email": "owner@test.local", "password": "secret123"})

# ------------------------------------------------- onboarding wizard
print("(c) onboarding wizard")
r = client.get("/app/onboarding")
check(r.status_code == 200, "wizard step 1 renders")
r = client.post("/app/onboarding", data={
    "name": "Test Dhaba", "language": "en",
    "owner_phone": "+919999999999", "tagline_en": "Tasty test food"})
check(r.status_code in (301, 302), "step 1 POST redirects")
bid = bid_from_location(r.headers["Location"])
check(f"/app/onboarding/{bid}/menu" in r.headers["Location"],
      "step 1 -> menu step")
biz = store.get_business(bid)
check(biz["status"] == "draft" and biz["name"] == "Test Dhaba",
      "business created as draft")

r = client.get(f"/app/onboarding/{bid}/menu")
check(r.status_code == 200, "wizard step 2 (menu) renders")

# menu builder JSON API
r = client.post(f"/app/api/business/{bid}/categories",
                json={"name_en": "Snacks", "name_hi": "नाश्ता", "emoji": "🍘"})
check(r.status_code == 200 and "id" in r.get_json(), "API: add category")
cid = r.get_json()["id"]
r = client.post(f"/app/api/categories/{cid}/items",
                json={"name_en": "Samosa", "name_hi": "समोसा",
                      "price": 25, "veg": 1, "description": "crispy"})
check(r.status_code == 200 and "id" in r.get_json(), "API: add item")
iid = r.get_json()["id"]
r = client.get(f"/app/api/business/{bid}/menu")
menu = r.get_json()["categories"]
check(len(menu) == 1 and menu[0]["items"][0]["name_en"] == "Samosa",
      "API: menu round-trips the item")
r = client.put(f"/app/api/items/{iid}", json={"price": 30})
check(r.status_code == 200, "API: update item")
check(store.get_menu(bid)[0]["items"][0]["price"] == 30, "price updated in db")
r = client.get(f"/app/business/{bid}/menu")
check(r.status_code == 200 and b"mbReload" in r.data and b"Add item" in r.data,
      "menu builder page renders (JS-driven via API)")

# step 3: details
r = client.post(f"/app/onboarding/{bid}/details", data={
    "hours_open": "09:00", "hours_close": "22:00",
    "address_en": "1 Test Road", "address_hi": "", "maps_link": ""})
check(r.status_code in (301, 302) and "faqs" in r.headers["Location"],
      "step 3 -> faqs step")

# step 4: faqs (POST adds one FAQ and stays; Continue -> welcome)
r = client.get(f"/app/onboarding/{bid}/faqs")
check(r.status_code == 200, "wizard step 4 renders")
r = client.post(f"/app/onboarding/{bid}/faqs", data={
    "faq_key": "timing", "keywords": "timing, hours",
    "answer_en": "Open 9am to 10pm.", "answer_hi": "सुबह 9 से रात 10 तक।"})
check(r.status_code in (301, 302), "adding FAQ redirects back to faq step")
# (template starter FAQs are seeded at creation, so assert by key)
check(any(f["faq_key"] == "timing" for f in store.list_faqs(bid)),
      "faq saved")
r = client.get(f"/app/onboarding/{bid}/faqs")
check(b"Continue to welcome" in r.data, "faq step links onward to welcome")

# step 5: welcome -> active
r = client.get(f"/app/onboarding/{bid}/welcome")
check(r.status_code == 200 and b"Test Dhaba" in r.data,
      "wizard step 5 renders with business name")
r = client.post(f"/app/onboarding/{bid}/welcome", data={})
check(r.status_code in (301, 302), "finish redirects")
check(store.get_business(bid)["status"] == "active",
      "business flipped to active")

# ------------------------------------------------- business home + pages
print("(d) business home, preview, settings, faqs, connect, checklist")
for path, needle in [
    (f"/app/business/{bid}", b"Test Dhaba"),
    (f"/app/business/{bid}/preview", b"Test Dhaba"),
    (f"/app/business/{bid}/faqs", b"timing"),
    (f"/app/business/{bid}/settings", b"Test Dhaba"),
    (f"/app/business/{bid}/connect", b"WhatsApp"),
    (f"/app/business/{bid}/checklist", b"Business Manager"),
]:
    r = client.get(path)
    check(r.status_code == 200 and needle in r.data,
          f"GET {path} renders")

# preview is wired to THIS business's content via /demo/message
r = client.post("/demo/message", json={
    "phone": "919000000001", "text": "menu", "business_id": bid})
blob = str(r.get_json())
check(r.status_code == 200 and "Snacks" in blob,
      "preview chat lists the new business category")
check("Butter Chicken" not in blob and "Starters" not in blob,
      "preview chat hides demo business menu")
r = client.post("/demo/message", json={
    "phone": "919000000001", "text": f"cmd:cat:{cid}", "business_id": bid})
blob = str(r.get_json())
check("Samosa" in blob and "₹30" in blob,
      "preview chat shows the new business item + updated price")

# settings update
r = client.post(f"/app/business/{bid}/settings", data={
    "name": "Test Dhaba", "tagline_en": "Even tastier",
    "tagline_hi": "", "language": "en",
    "hours_open": "09:00", "hours_close": "22:00", "last_booking": "21:30",
    "address_en": "1 Test Road", "address_hi": "", "maps_link": "",
    "owner_phone": "+919999999999",
    "welcome_en": "Welcome!", "welcome_hi": "स्वागत!"})
check(r.status_code in (301, 302), "settings save redirects")
check(store.get_business(bid)["tagline_en"] == "Even tastier",
      "settings persisted")

# ------------------------------------------------- simulated connect
print("(e) WhatsApp connect (simulated)")
r = client.post(f"/app/business/{bid}/connect/simulate")
check(r.status_code in (301, 302), "simulate redirects")
biz = store.get_business(bid)
check(biz["status"] == "connected", "status -> connected")
check(biz["whatsapp_phone_number_id"] == f"demo_pnid_{bid}",
      "fake phone_number_id stored")
check(store.get_whatsapp_token(bid) == "demo-token", "token decrypts")

# webhook now routes to the new business via its pnid
payload = {"entry": [{"changes": [{"value": {
    "metadata": {"phone_number_id": f"demo_pnid_{bid}"},
    "messages": [{"from": "919000000002", "id": "w1",
                  "text": {"body": "hi"}}]}}]}]}
r = client.post("/webhook", json=payload)
check(r.status_code == 200, "webhook 200 after connect")
check(store.count_messages(bid, "in") >= 1, "webhook routed to new business")

# ------------------------------------------------- ownership isolation
print("(f) cross-user isolation")
# same store, brand-new session -> second user must not see user 1's business
client2 = server.app.test_client()
client2.post("/app/signup", data={"email": "intruder@test.local",
                                  "password": "secret123",
                                  "confirm": "secret123"})
r = client2.get(f"/app/business/{bid}")
check(r.status_code == 404, "other user's business -> 404")
r = client2.get("/app/")
check(r.status_code == 200 and b"Test Dhaba" not in r.data,
      "intruder dashboard hides the business")
r = client2.post("/demo/message", json={
    "phone": "919000000003", "text": "menu", "business_id": bid})
check(r.status_code == 200, "public preview still works (by design)")

print(f"\nALL {PASS} DASHBOARD CHECKS PASSED ✔")
