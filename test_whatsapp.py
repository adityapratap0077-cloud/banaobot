"""Tests for the BanaoBot v2 WhatsApp connector + website embed.

Covers:
  - storage: whatsapp_connections CRUD, encrypted tokens, verify_token
    generation/preservation, bot linking (owner-scoped), enabled toggle.
  - GET /webhooks/whatsapp: subscribe success (challenge echoed) and
    failure (wrong/missing token -> 403).
  - POST /webhooks/whatsapp: text routes to the linked bot via
    brain.chat_with_prompt (mocked), per-sender history, Graph send
    (mocked _graph_post), read receipts; X-Hub-Signature-256 accept/
    reject; non-text ignored with 200; missing brain key -> honest
    reply; unknown phone_number_id -> 200, no crash; disabled
    connection -> honest reply, no AI call.
  - Dashboard /app/whatsapp: credentials form, webhook URL + verify
    token with no raw-token leakage, bot picker, pause/resume,
    disconnect, cross-user isolation.
  - Embed: GET /b/<token>?embed=1 -> 200 without site chrome; bot
    detail page contains both website snippets with the bot's token.

brain.chat_with_prompt is monkeypatched (no real Gemini call); the fake
delegates to the real function when the key is empty, exercising the
honest "not awake" path.

Usage: python3 test_whatsapp.py
Exits non-zero on the first failure.
"""

import hashlib
import hmac
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("DEMO_MODE", "true")

import brain
import server
import whatsapp
from storage import Store
from werkzeug.security import generate_password_hash

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


client, store = fresh_client()

EMAIL = "wa-owner@test.local"
PW = "secret123"
PROMPT = ("You are a friendly café assistant. You know the full menu and "
          "prices, and you answer warmly in English or Hindi.")
TEST_KEY = "AIza-test-key-1234567890"
PNID = "111222333444555"
WA_TOKEN = "EAAB-test-access-token-xyz"
APP_SECRET = "test-app-secret-abc"

uid = store.create_user(EMAIL, generate_password_hash(PW))
bid = store.create_bot(uid, "Cafe Bot", PROMPT)
bot = store.get_bot(bid)
share_token = bot["share_token"]

# ------------------------------------------------- (a) storage: connections
print("== (a) whatsapp_connections storage ==")

try:
    store.save_whatsapp_connection(uid, "", WA_TOKEN)
    check(False, "empty phone_number_id is rejected")
except ValueError:
    check(True, "empty phone_number_id is rejected (ValueError)")

try:
    store.save_whatsapp_connection(uid, PNID, "short")
    check(False, "short access token is rejected")
except ValueError:
    check(True, "short access token is rejected (ValueError)")

store.save_whatsapp_connection(uid, PNID, WA_TOKEN, APP_SECRET)
conn = store.get_whatsapp_connection(uid)
check(conn is not None and conn["phone_number_id"] == PNID
      and conn["enabled"] and conn["bot_id"] is None,
      "connection saved: pnid, enabled, no bot linked yet")
check(bool(conn.get("verify_token")) and len(conn["verify_token"]) >= 20,
      "a verify token was generated")
check("access_token_enc" not in conn and "access_token" not in conn,
      "public getter never exposes raw/encrypted tokens")
vtok1 = conn["verify_token"]

# update preserves the verify token + bot link + enabled flag
store.set_whatsapp_bot(uid, bid)
store.save_whatsapp_connection(uid, PNID, WA_TOKEN + "2", APP_SECRET)
conn = store.get_whatsapp_connection(uid)
check(conn["verify_token"] == vtok1 and conn["bot_id"] == bid
      and conn["enabled"],
      "re-saving preserves verify_token, bot link and enabled flag")

# secrets round-trip internally
sec = store._get_whatsapp_connection_secrets(uid)
check(sec["access_token"] == WA_TOKEN + "2"
      and sec["app_secret"] == APP_SECRET,
      "decrypted secrets round-trip (internal getter only)")

# lookups used by the webhook
by_pnid = store.get_whatsapp_connection_by_pnid(PNID)
check(by_pnid is not None and by_pnid["user_id"] == uid
      and by_pnid["access_token"] == WA_TOKEN + "2",
      "lookup by phone_number_id returns the connection with secrets")
check(store.get_whatsapp_connection_by_pnid("000") is None,
      "lookup by unknown phone_number_id returns None")
by_vtok = store.get_whatsapp_connection_by_verify_token(vtok1)
check(by_vtok is not None and by_vtok["user_id"] == uid,
      "lookup by verify_token returns the connection")

# bot linking is owner-scoped
uid_intruder = store.create_user("wa-intruder@test.local",
                                 generate_password_hash(PW))
check(store.set_whatsapp_bot(uid, bid) is True,
      "owner can link their own bot")
check(store.set_whatsapp_bot(uid, 999999) is False,
      "linking a nonexistent bot fails")
bid_intruder = store.create_bot(
    uid_intruder, "Intruder Bot",
    "An intruder bot with a sufficiently long prompt for testing.")
check(store.set_whatsapp_bot(uid, bid_intruder) is False,
      "linking another owner's bot fails")
check(store.set_whatsapp_bot(uid, None) is True
      and store.get_whatsapp_connection(uid)["bot_id"] is None,
      "bot can be unlinked")

check(store.set_whatsapp_enabled(uid, False) is True
      and store.get_whatsapp_connection(uid)["enabled"] is False,
      "connection can be disabled")
check(store.set_whatsapp_enabled(uid, True) is True
      and store.get_whatsapp_connection(uid)["enabled"] is True,
      "connection can be re-enabled")
check(store.delete_whatsapp_connection(uid) is True
      and store.get_whatsapp_connection(uid) is None,
      "connection can be deleted")
check(store.delete_whatsapp_connection(uid) is False,
      "deleting a missing connection returns False")

# re-create for the webhook tests (fresh verify token, bot linked, key set)
store.save_whatsapp_connection(uid, PNID, WA_TOKEN, APP_SECRET)
store.set_whatsapp_bot(uid, bid)
store.save_user_brain_key(uid, TEST_KEY)
conn = store.get_whatsapp_connection(uid)
VERIFY = conn["verify_token"]

# ------------------------------------------------- (b) subscribe handshake
print("== (b) GET /webhooks/whatsapp verification ==")


def verify_url(**q):
    qs = "&".join(f"{k}={v}" for k, v in q.items())
    return "/webhooks/whatsapp?" + qs


r = client.get(verify_url(**{"hub.mode": "subscribe",
                             "hub.verify_token": VERIFY,
                             "hub.challenge": "ch4llenge!"}))
check(r.status_code == 200 and r.get_data(as_text=True) == "ch4llenge!"
      and "text/plain" in r.content_type,
      "correct verify token -> 200 with the challenge as plain text")

r = client.get(verify_url(**{"hub.mode": "subscribe",
                             "hub.verify_token": "wrong",
                             "hub.challenge": "ch4llenge!"}))
check(r.status_code == 403, "wrong verify token -> 403")

r = client.get(verify_url(**{"hub.mode": "subscribe",
                             "hub.challenge": "ch4llenge!"}))
check(r.status_code == 403, "missing verify token -> 403")

r = client.get(verify_url(**{"hub.mode": "unsubscribe",
                             "hub.verify_token": VERIFY,
                             "hub.challenge": "ch4llenge!"}))
check(r.status_code == 403, "wrong hub.mode -> 403")

# ------------------------------------------------- (c) mock the brain + Graph
print("== (c) webhook message routing (mocked) ==")
real_chat = brain.chat_with_prompt
real_graph_post = whatsapp._graph_post
brain_calls = []
graph_calls = []


def fake_chat(api_key, bot_name, owner_prompt, history, user_text):
    brain_calls.append({"api_key": api_key, "bot_name": bot_name,
                        "owner_prompt": owner_prompt,
                        "history": list(history), "user_text": user_text})
    if not (api_key or "").strip():
        return real_chat(api_key, bot_name, owner_prompt, history,
                         user_text)
    assert bot_name == "Cafe Bot", "bot name not passed through"
    assert owner_prompt == PROMPT, "owner prompt not passed through"
    return "MOCK-REPLY: " + user_text


def fake_graph_post(pnid, access_token, payload):
    graph_calls.append({"pnid": pnid, "access_token": access_token,
                        "payload": payload})
    return {"messages": [{"id": "wamid.fake"}]}


brain.chat_with_prompt = fake_chat
whatsapp._graph_post = fake_graph_post


def wa_payload(text=None, pnid=PNID, wa_id="919999888877", mid="wamid.1",
               extra_msg=None):
    msg = {"from": wa_id, "id": mid, "timestamp": "1700000000"}
    if extra_msg is not None:
        msg.update(extra_msg)
    elif text is not None:
        msg["text"] = {"body": text}
    return {"object": "whatsapp_business_account",
            "entry": [{"id": "entry1", "changes": [{
                "field": "messages",
                "value": {"messaging_product": "whatsapp",
                          "metadata": {"display_phone_number": "15550001122",
                                       "phone_number_id": pnid},
                          "messages": [msg]}}]}]}


def post_wa(payload=None, secret=None, **kw):
    if payload is None:
        payload = wa_payload(**kw)
    body = json.dumps(payload)
    headers = {}
    if secret is not None:
        sig = hmac.new(secret.encode(), body.encode(),
                       hashlib.sha256).hexdigest()
        headers["X-Hub-Signature-256"] = "sha256=" + sig
    return client.post("/webhooks/whatsapp", data=body,
                       content_type="application/json", headers=headers)


def last_text_send():
    sends = [c for c in graph_calls
             if c["payload"].get("type") == "text"]
    return sends[-1] if sends else None


# signature is required (app secret is set on this connection)
r = post_wa(wa_payload("hello there"), secret=APP_SECRET)
check(r.status_code == 200, "valid signature -> 200")
check(len(brain_calls) == 1
      and brain_calls[0]["user_text"] == "hello there"
      and brain_calls[0]["api_key"] == TEST_KEY,
      "text message reaches the brain with the owner's key + bot prompt")
send = last_text_send()
check(send is not None and send["pnid"] == PNID
      and send["payload"]["to"] == "919999888877"
      and send["payload"]["text"]["body"].startswith("MOCK-REPLY"),
      "reply is sent via the Graph API to the sender")
check(send["access_token"] == WA_TOKEN,
      "the stored access token is used for the Graph call")
reads = [c for c in graph_calls if c["payload"].get("status") == "read"]
check(len(reads) == 1 and reads[0]["payload"]["message_id"] == "wamid.1",
      "incoming message is marked as read")

# second message -> history is passed
r = post_wa(wa_payload("and the prices?"), secret=APP_SECRET)
hist = brain_calls[-1]["history"]
check(len(hist) == 2 and hist[0] == ("user", "hello there")
      and hist[1][0] == "model"
      and hist[1][1].startswith("MOCK-REPLY")
      and brain_calls[-1]["user_text"] == "and the prices?",
      "per-sender conversation history reaches the brain")

# history is keyed per sender
brain_calls.clear()
r = post_wa(wa_payload("new person here", wa_id="911111111111"),
            secret=APP_SECRET)
check(brain_calls[-1]["history"] == [],
      "a different sender starts with empty history")

# ------------------------------------------------- (d) signature verification
print("== (d) X-Hub-Signature-256 ==")
brain_calls.clear()
graph_calls.clear()
r = post_wa(wa_payload("forged message"), secret="wrong-secret")
check(r.status_code == 200, "bad signature still answers 200 to Meta")
check(not brain_calls and not graph_calls,
      "bad signature -> message dropped (no brain, no send)")

r = post_wa(wa_payload("no signature header"))
check(r.status_code == 200 and not brain_calls and not graph_calls,
      "missing signature -> message dropped, still 200")

# connection without an app secret skips verification
store.save_whatsapp_connection(uid, PNID, WA_TOKEN, "")
store.set_whatsapp_bot(uid, bid)
r = post_wa(wa_payload("no secret needed"))
check(r.status_code == 200 and brain_calls
      and last_text_send() is not None,
      "no app secret set -> signature check skipped, message processed")
store.save_whatsapp_connection(uid, PNID, WA_TOKEN, APP_SECRET)
store.set_whatsapp_bot(uid, bid)

# ------------------------------------------------- (e) non-text + statuses
print("== (e) non-text payloads ==")
brain_calls.clear()
graph_calls.clear()
r = post_wa(wa_payload(extra_msg={"type": "image",
                                  "image": {"id": "img1"}}),
            secret=APP_SECRET)
check(r.status_code == 200 and not brain_calls and not graph_calls,
      "image message ignored with 200 (no brain, no send)")

status_payload = {"object": "whatsapp_business_account",
                  "entry": [{"id": "e1", "changes": [{
                      "field": "messages",
                      "value": {"messaging_product": "whatsapp",
                                "metadata": {"phone_number_id": PNID},
                                "statuses": [{"id": "wamid.1",
                                              "status": "delivered"}]}}]}]}
r = post_wa(status_payload, secret=APP_SECRET)
check(r.status_code == 200 and not brain_calls and not graph_calls,
      "status callbacks ignored with 200")

r = client.post("/webhooks/whatsapp", data="not json{{{",
                content_type="application/json")
check(r.status_code == 200, "malformed JSON -> 200, no crash")

# ------------------------------------------------- (f) missing brain key
print("== (f) missing brain key -> honest reply ==")
store.delete_user_brain_key(uid)
brain_calls.clear()
graph_calls.clear()
r = post_wa(wa_payload("are you awake?"), secret=APP_SECRET)
check(r.status_code == 200, "missing key still 200s")
send = last_text_send()
check(send is not None
      and "not awake" in send["payload"]["text"]["body"].lower(),
      "missing brain key -> the honest 'not awake' reply is sent")
check(brain_calls and brain_calls[0]["api_key"] == "",
      "honest path calls the brain with an empty key")
store.save_user_brain_key(uid, TEST_KEY)

# ------------------------------------------------- (g) unknown number / disabled
print("== (g) unknown pnid + disabled connection ==")
brain_calls.clear()
graph_calls.clear()
r = post_wa(pnid="000000000", text="hello?", secret=APP_SECRET)
check(r.status_code == 200 and not brain_calls and not graph_calls,
      "unknown phone_number_id -> 200, ignored, no crash")

store.set_whatsapp_enabled(uid, False)
r = post_wa(wa_payload("hello again"), secret=APP_SECRET)
send = last_text_send()
check(r.status_code == 200 and send is not None
      and "not awake" in send["payload"]["text"]["body"].lower()
      and all(c["api_key"] == "" for c in brain_calls),
      "disabled connection -> honest reply, never the AI brain")
store.set_whatsapp_enabled(uid, True)

# no bot linked -> honest reply too
store.set_whatsapp_bot(uid, None)
graph_calls.clear()
r = post_wa(wa_payload("anybody there?"), secret=APP_SECRET)
send = last_text_send()
check(send is not None
      and "not awake" in send["payload"]["text"]["body"].lower(),
      "no linked bot -> honest reply")
store.set_whatsapp_bot(uid, bid)

# ------------------------------------------------- (h) dashboard page + actions
print("== (h) /app/whatsapp dashboard ==")
client.post("/app/login", data={"email": EMAIL, "password": PW})
r = client.get("/app/whatsapp")
html = r.get_data(as_text=True)
check(r.status_code == 200
      and "/webhooks/whatsapp" in html
      and VERIFY in html,
      "whatsapp page shows the webhook URL and verify token")
check(WA_TOKEN not in html and "EAAB" not in html,
      "raw access token never rendered on the page")
check(PNID in html and "Cafe Bot" in html,
      "page shows the phone number ID and the linked bot")

r = client.post("/app/whatsapp",
                data={"action": "save", "phone_number_id": "bad!!",
                      "access_token": "x"})
check(r.status_code == 302
      and store.get_whatsapp_connection(uid)["phone_number_id"] == PNID,
      "invalid credentials form is rejected, connection untouched")

r = client.post("/app/whatsapp",
                data={"action": "save", "phone_number_id": "999888777",
                      "access_token": "EAAB-brand-new-token",
                      "app_secret": ""})
check(r.status_code == 302
      and store.get_whatsapp_connection(uid)["phone_number_id"] == "999888777"
      and store.get_whatsapp_connection(uid)["verify_token"] == VERIFY,
      "saving new credentials updates pnid, keeps verify token")

r = client.post("/app/whatsapp",
                data={"action": "toggle"})
check(r.status_code == 302
      and store.get_whatsapp_connection(uid)["enabled"] is False,
      "toggle pauses the connection")
r = client.post("/app/whatsapp",
                data={"action": "toggle"})
check(store.get_whatsapp_connection(uid)["enabled"] is True,
      "toggle resumes the connection")

r = client.post("/app/whatsapp", data={"action": "disconnect"})
check(r.status_code == 302
      and store.get_whatsapp_connection(uid) is None,
      "disconnect removes the connection")

r = client.get("/app/whatsapp")
check(r.status_code == 200
      and "Not connected yet" in r.get_data(as_text=True),
      "after disconnect the page shows the not-connected state")

# re-connect for the remaining tests
store.save_whatsapp_connection(uid, PNID, WA_TOKEN, APP_SECRET)
store.set_whatsapp_bot(uid, bid)

# cross-user isolation
client2 = server.app.test_client()
client2.post("/app/login",
             data={"email": "wa-intruder@test.local", "password": PW})
r = client2.get("/app/whatsapp")
html2 = r.get_data(as_text=True)
check(r.status_code == 200
      and PNID not in html2
      and store.get_whatsapp_connection(uid)["verify_token"] not in html2
      and "Not connected yet" in html2,
      "user B cannot see user A's connection (no pnid, no verify token)")
r = client2.post("/app/whatsapp",
                 data={"action": "setbot", "bot_id": str(bid)})
check(store.get_whatsapp_connection(uid)["bot_id"] == bid
      and store.get_whatsapp_connection(uid_intruder) is None,
      "user B cannot relink user A's connection to their own ends")
r = client2.post("/app/whatsapp", data={"action": "disconnect"})
check(store.get_whatsapp_connection(uid) is not None,
      "user B cannot disconnect user A's connection")
r = client2.get("/app/")
check(r.status_code == 200, "sanity: user B dashboard still works")

# unauthenticated
r = server.app.test_client().get("/app/whatsapp")
check(r.status_code == 302
      and r.headers["Location"].endswith("/app/login"),
      "anonymous /app/whatsapp redirects to login")

# ------------------------------------------------- (i) embed mode
print("== (i) ?embed=1 website embed ==")
client.post("/app/login", data={"email": EMAIL, "password": PW})
r = client.get(f"/b/{share_token}")
normal = r.get_data(as_text=True)
check(r.status_code == 200 and '<header class="topbar">' in normal,
      "normal public page carries the site header chrome")

r = client.get(f"/b/{share_token}?embed=1")
embed = r.get_data(as_text=True)
check(r.status_code == 200, "embed page returns 200")
check("<header" not in embed, "embed page has no <header> element")
check("chat-form" in embed and "Cafe Bot" in embed,
      "embed page keeps the working chat shell + bot name")
check(f"/b/{share_token}/chat" in embed,
      "embed page posts to the bot's chat endpoint")

r = client.get("/b/no-such-token?embed=1")
check(r.status_code == 404, "embed with a bad token -> 404")

# detail page snippets
r = client.get(f"/app/bots/{bid}")
html = r.get_data(as_text=True)
check("?embed=1" in html and share_token in html,
      "detail page embeds the bot's token in the ?embed=1 URL")
check("&lt;iframe" in html and "embed-iframe" in html,
      "detail page contains the inline iframe snippet")
check("#e85d26" in html and "embed-bubble" in html,
      "detail page contains the floating bubble snippet (orange button)")
check("position:fixed" in html,
      "bubble snippet keeps its fixed bottom-right positioning")

brain.chat_with_prompt = real_chat
whatsapp._graph_post = real_graph_post

print(f"\n{PASS} whatsapp/embed checks passed.")
