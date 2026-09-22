"""Tests for BanaoBot's universal templates + human voice.

Covers:
  (a) all six templates: welcome copy, button labels, catalog nouns
  (b) booking unit prompts per template (guests / students / patients ...)
  (c) shop enquiry flow -> owner alert (never enters date/time booking)
  (d) teacher demo-class booking end-to-end
  (e) cross-template isolation (no data leakage between businesses)
  (f) HUMAN VOICE: no reply anywhere contains bot/AI self-references or
      robotic phrasing; every repeated line rotates variants across calls
  (g) tone setting: per-template defaults + dashboard override changes voice
  (h) the bot uses the customer's name once it learns it
  (i) Hindi mode reads like natural Hinglish

Usage: python3 test_templates.py
Exits non-zero on the first failure.
"""

import os
import re
import sys
import tempfile
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import engine
import phrasing
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


def make_world():
    """In-memory store with one business per template + a send() helper."""
    store = Store(":memory:")
    clients = {}

    def client_for(bid, tag):
        phone = f"9191000000{tag:02d}"
        bundle = store.get_business_bundle(bid)

        def send(text):
            session = store.get_session(phone, bid)
            replies, new_session = engine.handle_message(
                phone, text, session, business=bundle, today=TODAY)
            events = new_session.pop("_events", [])
            for ev in events:
                if ev["type"] == "save_booking":
                    store.save_booking(ev["booking"], business_id=bid)
                elif ev["type"] == "owner_alert":
                    store.add_alert(phone, ev["reason"], business_id=bid)
            store.save_session(phone, new_session, business_id=bid)
            return replies, new_session, events

        return send

    bids = {}
    specs = [
        ("rest", "restaurant", "Bhoj House 2", 11),
        ("shop", "shop", "Sharma Store", 12),
        ("free", "freelancer", "Priya Designs", 13),
        ("clinic", "clinic", "City Clinic", 14),
        ("teach", "teacher", "Adiroxx Guitar Classes", 15),
        ("creator", "creator", "Ady Vlogs", 16),
    ]
    for key, tid, name, tag in specs:
        bid = store.create_business(1, name, template_id=tid,
                                    owner_phone="919876543210")
        # one category + one item so catalog browsing works everywhere
        cid = store.add_category(bid, f"{tid} cat", "", "🎯")
        store.add_item(cid, f"{tid} item", "", 100, veg=1, description="")
        bids[key] = bid
        clients[key] = client_for(bid, tag)
    return store, bids, clients, client_for


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


def titles(replies):
    out = []
    for r in replies:
        if r["type"] == "interactive" and r["interactive"]["type"] == "button":
            out += [b["reply"]["title"]
                    for b in r["interactive"]["action"]["buttons"]]
    return out


store, bids, clients, client_for = make_world()

# ------------------------------------------------------------------ (a) labels
print("(a) per-template welcome copy, buttons and catalog nouns")
expect = {
    "rest":    ("restaurant", "🍽 View Menu", "📅 Book a Table"),
    "shop":    ("shop", "🛍 Browse Products", "🛒 Enquire to Order"),
    "free":    ("freelancer", "💼 View Services", "📅 Book a Call"),
    "clinic":  ("clinic", "🏥 View Treatments", "📅 Book Appointment"),
    "teach":   ("teacher", "🎓 View Courses", "🎓 Book Free Demo"),
    "creator": ("creator", "✨ View Offerings", "📅 Book a Call"),
}
for key, (tid, cat_btn, act_btn) in expect.items():
    send = clients[key]
    r, s, _ = send("hi")
    body = bodies(r)[0]
    check(store.get_business(bids[key])["name"].split()[0] in body,
          f"{tid}: welcome mentions the business")
    ts = titles(r)
    check(cat_btn in ts, f"{tid}: catalog button '{cat_btn}'")
    check(act_btn in ts, f"{tid}: action button '{act_btn}'")
    check(all(len(t) <= 20 for t in ts), f"{tid}: all button titles <= 20 chars")
    # catalog browsing uses the template noun
    r, s, _ = send("cmd:menu")
    check(bodies(r)[0].split("\n")[0] != "", f"{tid}: catalog list renders")
    r, s, _ = send(f"cmd:cat:{store.get_menu(bids[key])[0]['id']}")
    check(f"{tid} item" in bodies(r)[0], f"{tid}: catalog item visible")

# ------------------------------------------------------------------ (b) units
print("(b) booking unit prompts per template")
unit_expect = {
    "rest": "guests", "free": "people", "clinic": "patients",
    "teach": "students", "creator": "attendees",
}
for key, unit in unit_expect.items():
    send = clients[key]
    send("hi")
    send("cmd:book")
    send("tomorrow")
    r, s, _ = send("8pm" if key == "rest" else "3pm")
    check(s["state"] == "book_size", f"{templates.get(store.get_business(bids[key])['template_id'])['name']}: reached unit step")
    check(unit in bodies(r)[0].lower(), f"unit prompt says '{unit}'")

# ------------------------------------------------------- (c) shop enquiry
print("(c) shop enquiry -> owner alert, never date/time booking")
send = client_for(bids["shop"], 21)
r, s, _ = send("hi")
ts = titles(r)
check("cmd:enquire" in reply_ids(r), "shop greeting offers Enquire (not Book)")
check("cmd:book" not in reply_ids(r), "shop greeting has no Book button")
r, s, _ = send("i want to order")
check(s["state"] == "enq_items", "'order' starts enquiry, not booking")
check("book_date" not in s["state"], "no date step for shops")
r, s, _ = send("2x Blue Shirt, 1x Jeans")
check(s["state"] == "enq_name", "items -> asks name")
r, s, _ = send("Rahul")
check(s["state"] == "enq_phone", "name -> asks phone")
r, s, _ = send("9876543210")
check(s["state"] == "enq_confirm", "phone -> confirm step")
check("Blue Shirt" in bodies(r)[0], "enquiry summary shows items")
r, s, ev = send("cmd:confirm_enquiry")
check(s["state"] == "idle", "enquiry confirmed -> idle")
check(len(ev) == 1 and ev[0]["type"] == "owner_alert", "owner_alert emitted")
check("New order enquiry" in ev[0]["reason"], "alert is an order enquiry")
check("Blue Shirt" in ev[0]["reason"] and "Rahul" in ev[0]["reason"],
      "alert carries items + name + phone")
check(store.count_bookings(bids["shop"]) == 0, "no booking row for enquiry")
alerts = store.list_alerts(bids["shop"])
check(any("New order enquiry" in a["reason"] for a in alerts),
      "enquiry alert persisted")

# ------------------------------------------------- (d) teacher booking
print("(d) teacher demo-class booking end-to-end")
send = client_for(bids["teach"], 22)
r, s, _ = send("hi")
check("cmd:book" in reply_ids(r), "teacher greeting offers Book (demo)")
r, s, _ = send("cmd:book")
check(s["state"] == "book_date", "Book Free Demo button starts booking")
send("tomorrow")
r, s, _ = send("4pm")
check("students" in bodies(r)[0].lower(), "teacher unit prompt says students")
send("3")
r, s, _ = send("Priya")
r, s, _ = send("9876543210")
summary = bodies(r)[0]
check("students" in summary.lower(), "summary uses students")
r, s, ev = send("cmd:confirm_booking")
check(len(ev) == 1 and ev[0]["type"] == "save_booking", "teacher booking saved")
check(ev[0]["booking"]["id"] in bodies(r)[0], "confirmation shows booking id")
check(store.count_bookings(bids["teach"]) == 1, "teacher booking in sqlite")

# ------------------------------------------------------------ (e) isolation
print("(e) cross-template isolation")
send_t, send_r = client_for(bids["teach"], 31), client_for(bids["rest"], 32)
rt, _, _ = send_r("hi")
tt, _, _ = send_t("hi")
check("Bhoj House 2" in bodies(rt)[0], "restaurant welcome is its own")
check("Adiroxx Guitar Classes" in bodies(tt)[0], "teacher welcome is its own")
check("Bhoj House 2" not in bodies(tt)[0], "restaurant name never leaks to teacher")
check("Adiroxx Guitar Classes" not in bodies(rt)[0], "teacher name never leaks to restaurant")
r, _, _ = send_t("cmd:menu")
_, _, _ = send_r("cmd:menu")
rest_cat = store.get_menu(bids["rest"])[0]["id"]
teach_cat = store.get_menu(bids["teach"])[0]["id"]
rt, _, _ = send_r(f"cmd:cat:{rest_cat}")
tt, _, _ = send_t(f"cmd:cat:{teach_cat}")
check("restaurant item" in bodies(rt)[0], "restaurant sees its catalog")
check("teacher item" in bodies(tt)[0], "teacher sees its catalog")
check("restaurant item" not in bodies(tt)[0], "restaurant catalog never leaks to teacher")
# alert isolation
check(all("Blue Shirt" not in a["reason"]
          for a in store.list_alerts(bids["teach"])),
      "shop enquiry alert not visible to teacher")

# ------------------------------------------------------ (f) human voice
print("(f) human voice: no bot/AI self-reference, no robotic phrasing")
# all tone packs expose the exact same key set, so no tone can KeyError
base = set(phrasing.PACKS["friendly"]["en"])
for tone in ("friendly", "professional", "casual"):
    for lang in ("en", "hi"):
        check(set(phrasing.PACKS[tone][lang]) == base,
              f"{tone}/{lang} pack has the full key set")
SELF_REF = re.compile(
    r"\bi\s*am\s+(an?\s+)?(bot|ai\b|artificial intelligence|digital assistant|assistant)\b"
    r"|\bi'm\s+(a|an)\s+(bot|ai|assistant)\b"
    r"|\bas\s+an\s+ai\b",
    re.IGNORECASE,
)
ROBOTIC = re.compile(
    r"please select (from the following|an) option"
    r"|kindly provide"
    r"|i('m| am) still learning",
    re.IGNORECASE,
)

# sweep: every template x tone x lang, many flows, collect all reply text
texts = []
for tid in templates.ids():
    bid = store.create_business(1, f"Voice {tid}", template_id=tid,
                                owner_phone="919876543210")
    bundle = store.get_business_bundle(bid)
    for tone in ("friendly", "professional", "casual"):
        bundle["tone"] = tone
        for lang in ("en", "hi"):
            phone = f"9192000{abs(hash((tid, tone, lang))) % 9000 + 1000}"

            def vsend(text, _bundle=bundle, _phone=phone, _lang=lang, _bid=bid):
                session = store.get_session(_phone, _bid) or {}
                session["lang"] = _lang
                replies, ns = engine.handle_message(
                    _phone, text, session, business=_bundle, today=TODAY)
                ns.pop("_events", None)
                store.save_session(_phone, ns, business_id=_bid)
                return replies

            flows = ["hi", "xyzqwe", "human",
                     "cmd:book", "tomorrow", "8pm", "2", "R",
                     "Ravi", "9876543210", "cmd:confirm_booking",
                     "cmd:menu", "cmd:enquire", "2 shirts", "Ravi",
                     "9876543210", "cmd:confirm_enquiry", "cancel"]
            for msg in flows:
                try:
                    for r in vsend(msg):
                        texts.extend(bodies([r]))
                except Exception:
                    pass  # flow mismatches are fine; we only scan text

for text in texts:
    check(not SELF_REF.search(text),
          f"no bot/AI self-reference in: {text[:60]!r}")
    check(not ROBOTIC.search(text),
          f"no robotic phrasing in: {text[:60]!r}")
print(f"    scanned {len(texts)} reply texts — all human-voiced ✔")

# rotation: the same repeated line must vary across calls (fresh session)
print("    variant rotation")
send = client_for(bids["rest"], 41)
send("hi")
seen = set()
for _ in range(6):
    r, s, _ = send("blarg123")
    seen.add(bodies(r)[0].split("\n\n")[0])  # fallback line (hint is constant)
check(len(seen) >= 3, f"fallback rotates across calls ({len(seen)} variants seen)")
# per-key determinism: a fresh conversation starts at variant[0]
phone2 = "919199999901"
bundle = store.get_business_bundle(bids["rest"])
session = store.get_session(phone2, bids["rest"])
replies, ns = engine.handle_message(phone2, "blarg123", session,
                                    business=bundle, today=TODAY)
check("didn't quite get that" in bodies(replies)[0],
      "first fallback is the canonical variant[0]")

# ------------------------------------------------------------------ (g) tone
print("(g) tone defaults and overrides")
defaults = {"rest": "friendly", "shop": "friendly", "free": "professional",
            "clinic": "professional", "teach": "friendly", "creator": "casual"}
for key, want in defaults.items():
    b = store.get_business_bundle(bids[key])
    check(b["tone"] == want, f"{key}: default tone is {want}")

# same line, different tone -> different voice
bid = bids["teach"]
bundle = store.get_business_bundle(bid)
session = store.get_session("919199999902", bid)
bundle_f = dict(bundle, tone="friendly")
bundle_c = dict(bundle, tone="casual")
rf, _ = engine.handle_message("919199999902", "blarg123", None,
                              business=bundle_f, today=TODAY)
rc, _ = engine.handle_message("919199999903", "blarg123", None,
                              business=bundle_c, today=TODAY)
check(bodies(rf)[0] != bodies(rc)[0], "tone changes the phrasing")
# dashboard override persists
store.update_business(bid, tone="casual")
check(store.get_business_bundle(bid)["tone"] == "casual",
      "tone override saved via update_business")

# ------------------------------------------------------- (h) name usage
print("(h) bot uses the customer's name once learned")
send = clients["free"]
send("hi")
send("cmd:book")
send("tomorrow")
send("3pm")
send("1")
r, s, _ = send("Rahul Sharma")
check(s["data"].get("cust_name") == "Rahul Sharma", "name stored in session")
send("9876543210")
r, s, ev = send("cmd:confirm_booking")
check("Rahul Sharma" in bodies(r)[0], "confirmation uses the name")
r, s, _ = send("blarg123")
check("Rahul" in bodies(r)[0], "later fallback uses the name")

# ------------------------------------------------------- (i) Hinglish
print("(i) Hindi mode reads like natural Hinglish")
send = client_for(bids["teach"], 51)
r, s, _ = send("/hindi")
r, s, _ = send("namaste")
body = bodies(r)[0]
check("swagat" in body.lower(), "Hindi welcome is Hinglish")
r, s, _ = send("blarg123")
fb = bodies(r)[0].lower()
check("samajh" in fb and "👇" in bodies(r)[0],
      "Hindi fallback is Hinglish, not textbook Hindi")

print(f"\nALL {PASS} CHECKS PASSED ✔")
