"""HTTP integration tests for the BanaoBot v2 dashboard (/app/*) + public bots.

Covers the prompt-first owner journey:
  signup validation -> signup -> login -> bot library -> new bot from one
  prompt -> bot page (edit prompt, preview chat, share link, delete) ->
  settings (brain key save/reject/remove) -> public /b/<token> chat ->
  cross-user isolation (owner-only routes 404 for other users).

brain.chat_with_prompt is monkeypatched globally (dashboard and server both
`import brain`), so no real Gemini call is ever made. The fake delegates to
the real function when the owner has no key, exercising the honest
"not awake" path.

Usage: python3 test_dashboard.py
Exits non-zero on the first failure. Requires dashboard.py + templates/.
Template-render checks skip (with a note) when the template file is missing,
e.g. the design pass hasn't landed it yet; the suite then exits non-zero at
the end so the gap is visible instead of silently green.
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("DEMO_MODE", "true")

import brain
import server
from storage import Store
from werkzeug.security import generate_password_hash

PASS = 0
SKIPPED = []


def check(cond, label):
    global PASS
    if not cond:
        print(f"  FAIL: {label}")
        sys.exit(1)
    PASS += 1
    print(f"  ok: {label}")


def check_page(cond, label, template):
    """Render-dependent check: skips (with a note) when the template file is
    missing instead of failing on a TemplateNotFound 500."""
    if template not in AVAILABLE_TEMPLATES:
        SKIPPED.append(label)
        print(f"  skip: {label} (template {template} missing)")
        return
    check(cond, label)


def fresh_client():
    """Rebind server to a fresh in-memory DB and return a test client."""
    store = Store(":memory:")
    server.store = store
    server.app.config["store"] = store
    return server.app.test_client(), store


client, store = fresh_client()

# Which render templates actually exist right now (the design pass is
# concurrent with this suite; a missing template must skip, not fail).
REQUIRED_TEMPLATES = ("dash_signup.html", "dash_login.html", "dash_index.html",
                      "dash_bot_new.html", "dash_bot_detail.html",
                      "dash_settings.html", "public_chat.html",
                      "public_404.html")
AVAILABLE_TEMPLATES = set()
for _t in REQUIRED_TEMPLATES:
    try:
        server.app.jinja_env.get_template(_t)
        AVAILABLE_TEMPLATES.add(_t)
    except Exception:
        pass
_missing = [t for t in REQUIRED_TEMPLATES if t not in AVAILABLE_TEMPLATES]
if _missing:
    print(f"note: templates missing, related checks will skip: {_missing}")

EMAIL = "owner@test.local"
PW = "secret123"
BOT_NAME = "Helper Bot"
PROMPT = ("You are a friendly café assistant. You know the full menu, prices "
          "and opening hours, and you answer warmly in English or Hindi.")
PROMPT2 = ("You are a friendly café assistant who also remembers regulars' "
           "orders and suggests the daily special every morning.")
TEST_KEY = "AIza-test-key-1234567890"

# ------------------------------------------------- (a) auth gating
print("== (a) auth gating ==")
r = client.get("/app/")
check(r.status_code == 302 and r.headers["Location"].endswith("/app/login"),
      "anonymous /app/ redirects to /app/login")

# ------------------------------------------------- (b) signup validation
print("== (b) signup validation ==")


def anon_signup(data):
    return server.app.test_client().post("/app/signup", data=data)


r = anon_signup({"email": "not-an-email", "password": PW, "confirm": PW})
check_page(r.status_code == 200
           and "valid email" in r.get_data(as_text=True).lower(),
           "signup rejects a bad email", "dash_signup.html")

r = anon_signup({"email": "a@b.co", "password": "abc", "confirm": "abc"})
check_page(r.status_code == 200
           and "at least 6 characters" in r.get_data(as_text=True),
           "signup rejects a short password", "dash_signup.html")

r = anon_signup({"email": "a@b.co", "password": PW, "confirm": "different"})
check_page(r.status_code == 200
           and "do not match" in r.get_data(as_text=True),
           "signup rejects mismatched passwords", "dash_signup.html")

# ------------------------------------------------- (c) signup -> library
print("== (c) signup -> library ==")
r = client.post("/app/signup",
                data={"email": EMAIL, "password": PW, "confirm": PW})
check(r.status_code == 302 and r.headers["Location"].endswith("/app/"),
      "signup succeeds and lands on /app/")

r = client.get("/app/")
html = r.get_data(as_text=True)
check_page(r.status_code == 200 and "No bots yet" in html
           and "/app/bots/new" in html,
           "empty library renders with a create-bot link", "dash_index.html")

r = anon_signup({"email": EMAIL, "password": PW, "confirm": PW})
check_page(r.status_code == 200
           and "already registered" in r.get_data(as_text=True).lower(),
           "duplicate signup shows a friendly error", "dash_signup.html")

# ------------------------------------------------- (d) logout -> login
print("== (d) logout -> login ==")
client.get("/app/logout")
r = client.get("/app/")
check(r.status_code == 302 and r.headers["Location"].endswith("/app/login"),
      "after logout, /app/ redirects to login again")

r = server.app.test_client().post(
    "/app/login", data={"email": EMAIL, "password": "wrong"})
check_page(r.status_code == 200
           and "Invalid email or password" in r.get_data(as_text=True),
           "login with the wrong password shows an error", "dash_login.html")

r = client.post("/app/login", data={"email": EMAIL, "password": PW})
check(r.status_code == 302 and r.headers["Location"].endswith("/app/"),
      "login succeeds and lands on /app/")

# ------------------------------------------------- (e) create bot from one prompt
print("== (e) create bot from one prompt ==")
r = client.post("/app/bots/new", data={"name": BOT_NAME, "prompt": PROMPT})
loc = r.headers.get("Location", "")
m = re.search(r"/app/bots/(\d+)$", loc)
check(r.status_code == 302 and m,
      "create bot from one prompt -> 302 to /app/bots/<id>")
bid = int(m.group(1))

r = client.post("/app/bots/new", data={"name": "Tiny", "prompt": "too short"})
check_page(r.status_code == 200
           and "too short" in r.get_data(as_text=True).lower(),
           "short prompt is rejected with a 'too short' error (200)",
           "dash_bot_new.html")

r = client.get("/app/")
check_page(r.status_code == 200 and BOT_NAME in r.get_data(as_text=True),
           "library lists the new bot", "dash_index.html")

# ------------------------------------------------- (f) bot page: prompt, share link, edit
print("== (f) bot page ==")
bot = store.get_bot(bid)
token = bot["share_token"]
check(bool(token), "new bot has a share token")

r = client.get(f"/app/bots/{bid}")
html = r.get_data(as_text=True)
check_page(r.status_code == 200 and PROMPT in html
           and ("/b/" + token) in html,
           "detail page shows the prompt text and the /b/<token> share link",
           "dash_bot_detail.html")

r = client.post(f"/app/bots/{bid}",
                data={"name": BOT_NAME, "prompt": PROMPT2})
check(r.status_code == 302 and store.get_bot(bid)["prompt"] == PROMPT2,
      "editing the prompt updates the bot")

r = client.post(f"/app/bots/{bid}",
                data={"name": BOT_NAME, "prompt": "tiny"},
                follow_redirects=True)
html = r.get_data(as_text=True)
check_page("too short" in html.lower()
           and store.get_bot(bid)["prompt"] == PROMPT2,
           "short prompt edit is rejected and the old prompt is kept",
           "dash_bot_detail.html")

# ------------------------------------------------- (g) preview chat WITHOUT a key
print("== (g) preview chat without a brain key ==")
r = client.post(f"/app/bots/{bid}/chat", json={"message": "hello there"})
data = r.get_json()
check(r.status_code == 200 and data["ok"]
      and "not awake" in data["reply"].lower(),
      "preview chat without a key returns the honest 'not awake' message")

# ------------------------------------------------- (h) settings: brain key
print("== (h) settings: brain key ==")
uid = store.get_user_by_email(EMAIL)["id"]
r = client.post("/app/settings",
                data={"action": "save", "brain_key": TEST_KEY})
check(r.status_code == 302 and store.has_user_brain_key(uid),
      "saving a brain key stores it (has_user_brain_key)")

r = client.get("/app/settings")
html = r.get_data(as_text=True)
check_page(r.status_code == 200
           and "connected" in html.lower()
           and TEST_KEY not in html,
           "settings page shows the key as connected (raw key never rendered)",
           "dash_settings.html")

r = client.post("/app/settings",
                data={"action": "save", "brain_key": "short"})
check(r.status_code == 302 and store.has_user_brain_key(uid)
      and store.get_user_brain_key(uid) == TEST_KEY,
      "a short key is rejected and the saved key is untouched")

# ------------------------------------------------- (i) preview chat WITH a key (mocked)
print("== (i) preview chat with a brain key (mocked Gemini) ==")
real_chat_with_prompt = brain.chat_with_prompt
calls = []


def fake_chat_with_prompt(api_key, bot_name, owner_prompt, history,
                          user_text):
    calls.append({"api_key": api_key, "bot_name": bot_name,
                  "owner_prompt": owner_prompt, "history": list(history),
                  "user_text": user_text})
    if not (api_key or "").strip():
        # no key: behave exactly like the real function (honest message)
        return real_chat_with_prompt(api_key, bot_name, owner_prompt,
                                     history, user_text)
    assert bot_name == BOT_NAME, \
        f"bot name not passed through: {bot_name!r}"
    assert owner_prompt == PROMPT2, "owner prompt not passed through"
    return "MOCK-REPLY: " + user_text


brain.chat_with_prompt = fake_chat_with_prompt

r = client.post(f"/app/bots/{bid}/chat",
                json={"message": "what's on the menu?"})
data = r.get_json()
check(r.status_code == 200 and data["ok"]
      and data["reply"].startswith("MOCK-REPLY"),
      "preview chat with a key returns the monkeypatched reply "
      "(mock asserted the bot name + owner prompt were passed in)")

r = client.post(f"/app/bots/{bid}/chat", json={"message": "and the prices?"})
hist = calls[-1]["history"]
check(len(hist) >= 2 and hist[-2][0] == "user" and hist[-1][0] == "model"
      and "what's on the menu?" in hist[-2][1]
      and hist[-1][1].startswith("MOCK-REPLY"),
      "second preview message passes the conversation history to the brain")

# ------------------------------------------------- (j) public share link
print("== (j) public share link ==")
r = client.get(f"/b/{token}")
check_page(r.status_code == 200 and BOT_NAME in r.get_data(as_text=True),
           "GET /b/<token> renders the public chat page with the bot name",
           "public_chat.html")

r = client.post(f"/b/{token}/chat", json={"message": "hi bot"})
data = r.get_json()
check(r.status_code == 200 and data["ok"]
      and data["reply"].startswith("MOCK-REPLY"),
      "POST /b/<token>/chat returns the mock reply (owner key, no login)")

r = client.get("/b/no-such-token")
check_page(r.status_code == 404,
           "bad token -> 404 on the public page", "public_404.html")

r = client.post("/b/no-such-token/chat", json={"message": "hi"})
check(r.status_code == 404 and not r.get_json()["ok"],
      "bad token -> 404 on the public chat endpoint")

# a keyless owner's bot: public chat must stay honest (mock delegates to real)
uid2 = store.create_user("keyless@test.local",
                         generate_password_hash(PW))
bid2 = store.create_bot(
    uid2, "Keyless Bot",
    "You are a quiet bot with no brain key attached, used for testing.")
token2 = store.get_bot(bid2)["share_token"]
r = client.post(f"/b/{token2}/chat", json={"message": "hello?"})
data = r.get_json()
check(r.status_code == 200 and data["ok"]
      and "not awake" in data["reply"].lower(),
      "public chat without an owner key returns the honest 'not awake' message")

# ------------------------------------------------- (k) cross-user isolation
print("== (k) cross-user isolation ==")
client2 = server.app.test_client()
client2.post("/app/signup", data={"email": "intruder@test.local",
                                  "password": PW, "confirm": PW})
r = client2.get(f"/app/bots/{bid}")
check(r.status_code == 404, "another user's bot page -> 404")
r = client2.post(f"/app/bots/{bid}/chat", json={"message": "snoop"})
check(r.status_code == 404, "another user's preview chat -> 404")
r = client2.post(f"/app/bots/{bid}/delete")
check(r.status_code == 404, "another user's bot delete -> 404")

# ------------------------------------------------- (l) delete own bot
print("== (l) delete bot ==")
r = client.post(f"/app/bots/{bid}/delete")
check(r.status_code == 302 and r.headers["Location"].endswith("/app/"),
      "deleting your own bot redirects to /app/")

r = client.get("/app/")
check_page(r.status_code == 200 and BOT_NAME not in r.get_data(as_text=True),
           "deleted bot is gone from the library", "dash_index.html")

r = client.get(f"/b/{token}")
check_page(r.status_code == 404,
           "deleted bot's public link 404s", "public_404.html")

# ------------------------------------------------- (m) key removal
print("== (m) key removal ==")
bid3 = store.create_bot(
    uid, "Second Bot",
    "You are a second test bot with a sufficiently long prompt for this.")
r = client.post("/app/settings", data={"action": "remove"})
check(r.status_code == 302 and not store.has_user_brain_key(uid),
      "removing the brain key clears it")

r = client.post(f"/app/bots/{bid3}/chat", json={"message": "are you awake?"})
data = r.get_json()
check(r.status_code == 200 and data["ok"]
      and "not awake" in data["reply"].lower(),
      "after key removal the preview is honest again ('not awake')")

# ------------------------------------------------- (n) share tokens are unique
print("== (n) share tokens ==")
t2 = store.get_bot(bid2)["share_token"]
t3 = store.get_bot(bid3)["share_token"]
check(bool(t2) and bool(t3) and t2 != t3,
      "two bots get different share tokens")

brain.chat_with_prompt = real_chat_with_prompt

if SKIPPED:
    print(f"\n{PASS} dashboard checks passed, "
          f"{len(SKIPPED)} skipped (templates missing).")
    for label in SKIPPED:
        print(f"  skipped: {label}")
    sys.exit(1)
print(f"\n{PASS} dashboard checks passed.")
