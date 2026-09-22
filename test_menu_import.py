"""Tests for the menu auto-import (menu_import.py + dashboard import routes).

Covers: price/name/category parsing across common menu formats, veg
guessing, junk-line filtering, and the dashboard parse -> review -> save
journey that builds a real catalogue from pasted text.

Usage: python3 test_menu_import.py
Exits non-zero on the first failure.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("DEMO_MODE", "true")

from menu_import import parse_menu_text

PASS = 0


def check(cond, label):
    global PASS
    if not cond:
        print(f"  FAIL: {label}")
        sys.exit(1)
    PASS += 1
    print(f"  ok: {label}")


def items_of(groups):
    return [(g["category"], i["name"], i["price"])
            for g in groups for i in g["items"]]


# ------------------------------------------------- (a) parser formats
print("(a) price formats")
groups = parse_menu_text(
    "Paneer Tikka ............ ₹250\n"
    "Chicken 65 - Rs. 220\n"
    "Masala Dosa | 120\n"
    "Butter Chicken 320/-\n"
    "Dal Fry ₹ 180\n"
    "Gulab Jamun (4 pc) Rs.99\n"
)
got = {name: price for _, name, price in items_of(groups)}
check(got.get("Paneer Tikka") == 250, "₹ price with dot leaders")
check(got.get("Chicken 65") == 220, "Rs. price with dash")
check(got.get("Masala Dosa") == 120, "bare trailing number")
check(got.get("Butter Chicken") == 320, "trailing /- price")
check(got.get("Dal Fry") == 180, "₹ with space")
check(got.get("Gulab Jamun") == 99, "Rs. without space + (desc)")

# ------------------------------------------------- (b) categories
print("(b) category headers")
groups = parse_menu_text(
    "STARTERS\nPaneer Tikka 250\n"
    "## Main Course\nButter Chicken 320\n"
    "Desserts:\nGulab Jamun 99\n"
    "--- Breads ---\nButter Naan 40\n"
)
cats = [g["category"] for g in groups]
check(cats == ["Starters", "Main Course", "Desserts", "Breads"],
      f"ALL-CAPS / ## / colon / dashes headers -> {cats}")
check(all(g["emoji"] for g in groups), "every category gets an emoji")

# ------------------------------------------------- (c) veg guessing
print("(c) veg / non-veg guess")
groups = parse_menu_text("Chicken Curry 300\nPalak Paneer 220\nEgg Curry 180\n")
veg = {i["name"]: i["veg"] for g in groups for i in g["items"]}
check(veg["Chicken Curry"] == 0, "chicken -> non-veg")
check(veg["Palak Paneer"] == 1, "paneer -> veg")
check(veg["Egg Curry"] == 0, "egg -> non-veg")

# ------------------------------------------------- (d) descriptions + junk
print("(d) descriptions and junk lines")
groups = parse_menu_text(
    "OUR MENU\n"
    "Starters\n"
    "Paneer Tikka (smoky, mint chutney) 250\n"
    "Call +91 98765 43210 for orders\n"
    "Open 11am - 11pm\n"
    "www.example.com\n"
)
its = items_of(groups)
check(len(its) == 1 and its[0][1] == "Paneer Tikka", "junk lines ignored")
desc = groups[0]["items"][0]["description"]
check(desc == "smoky, mint chutney", f"parenthetical -> description ({desc!r})")

# ------------------------------------------------- (e) no items -> empty
print("(e) empty input")
check(parse_menu_text("") == [], "empty text -> no groups")
check(parse_menu_text("Welcome to our shop!\nCall us anytime.") == [],
      "text with no prices -> no groups")

# ------------------------------------------------- (f) dashboard journey
print("(f) dashboard parse -> review -> save")

import server
from storage import Store

store = Store(":memory:")
server.store = store
server.app.config["store"] = store
client = server.app.test_client()

client.post("/app/signup", data={"email": "imp@test.local",
                                 "password": "secret123",
                                 "confirm": "secret123"})
r = client.post("/app/onboarding/basics?template=restaurant", data={
    "template": "restaurant", "name": "Import Dhaba", "language": "en",
    "owner_phone": "919999999999", "tagline_en": "", "tagline_hi": "",
})
import re
bid = int(re.search(r"/(\d+)/", r.headers["Location"]).group(1))

r = client.get(f"/app/business/{bid}/menu/import")
check(r.status_code == 200 and "Auto-build" in r.get_data(as_text=True),
      "GET import page renders")

r = client.post(f"/app/business/{bid}/menu/import/parse", data={
    "menu_text": "STARTERS\nPaneer Tikka 250\nChicken 65 220\n\n"
                 "Desserts:\nGulab Jamun 99\n"})
html = r.get_data(as_text=True)
check(r.status_code == 200 and "3 items found" in html,
      "parse finds 3 items")
check("Paneer Tikka" in html and "Gulab Jamun" in html,
      "review page lists parsed items")

# save: keep Paneer Tikka + Gulab Jamun, skip Chicken 65
r = client.post(f"/app/business/{bid}/menu/import/save", data={
    "cat_0": "Starters", "emoji_0": "🥗",
    "name_0_0": "Paneer Tikka", "price_0_0": "250", "desc_0_0": "",
    "name_0_1": "Chicken 65", "price_0_1": "220", "desc_0_1": "",
    "skip_0_1": "on", "nonveg_0_1": "on",
    "cat_1": "Desserts", "emoji_1": "🍨",
    "name_1_0": "Gulab Jamun", "price_1_0": "99", "desc_1_0": "4 pc",
}, follow_redirects=False)
check(r.status_code == 302, "save redirects to menu page")

menu = store.get_menu(bid)
names = [i["name_en"] for c in menu for i in c["items"]]
check("Paneer Tikka" in names and "Gulab Jamun" in names,
      "saved items land in the catalogue")
check("Chicken 65" not in names, "skipped item is not saved")
check(any(c["name_en"] == "Desserts" for c in menu),
      "categories created from headers")

# empty paste -> friendly error, no crash
r = client.post(f"/app/business/{bid}/menu/import/parse",
                data={"menu_text": "hello world no prices here"})
check(r.status_code == 200 and "find any items with prices" in
      r.get_data(as_text=True), "no-price text -> helpful error")

# cross-user isolation: another user can't import into this business
client.get("/app/logout")
client.post("/app/signup", data={"email": "imp2@test.local",
                                 "password": "secret123",
                                 "confirm": "secret123"})
r = client.get(f"/app/business/{bid}/menu/import")
check(r.status_code == 404, "other user's import page -> 404")

print(f"\nALL {PASS} MENU-IMPORT CHECKS PASSED ✔")
