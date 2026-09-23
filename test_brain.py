"""Tests for the BanaoBot "brain" (optional Gemini LLM layer).

Covers:
  (a) brain_on() gating
  (b) build_system_prompt() carries business knowledge + guardrails
  (c) chat() success path (mocked HTTP) — payload shape, history roles
  (d) chat() failure modes -> None (network error, malformed response,
      empty key, empty text)
  (e) storage: brain key round-trips encrypted, clear removes it
  (f) engine: idle gibberish with brain on -> brain reply (not the generic
      fallback), history recorded, quick-menu buttons still attached
  (g) engine: brain API failure -> classic generic fallback (never breaks)
  (h) engine: brain off -> classic generic fallback

Usage: python3 test_brain.py
Exits non-zero on the first failure.
"""

import copy
import io
import json
import os
import sys
import tempfile
import urllib.error
from datetime import date
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import brain
import engine
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


def biz_with_brain(on=True, key="test-key-123"):
    b = copy.deepcopy(engine.default_business())
    b["brain_enabled"] = on
    b["brain_key"] = key if on else ""
    return b


# ---------------------------------------------------------------------------
# (a) brain_on()
# ---------------------------------------------------------------------------
print("== (a) brain_on gating ==")
check(brain.brain_on({"brain_enabled": 1, "brain_api_key_enc": "fernet1:x"}),
      "on when enabled + key present")
check(not brain.brain_on({"brain_enabled": 0, "brain_api_key_enc": "fernet1:x"}),
      "off when disabled")
check(not brain.brain_on({"brain_enabled": 1, "brain_api_key_enc": ""}),
      "off when key missing")
check(not brain.brain_on({"brain_enabled": 1}),
      "off when key field absent")
check(not brain.brain_on(None), "off when biz is None")

# ---------------------------------------------------------------------------
# (b) build_system_prompt()
# ---------------------------------------------------------------------------
print("== (b) system prompt ==")
biz = biz_with_brain()
prompt = brain.build_system_prompt(biz)
check(biz["name"] in prompt, "prompt names the business")
check("₹" in prompt or "paneer" in prompt.lower(), "prompt carries menu knowledge")
check("never invent" in prompt.lower() or "NEVER invent" in prompt,
      "prompt has the no-hallucination rule")
check("language" in prompt.lower(), "prompt covers language matching")
check("AI" in prompt, "prompt keeps the bot in character (no AI talk)")
check("button" in prompt.lower(), "prompt routes bookings to buttons")

# ---------------------------------------------------------------------------
# (c) chat() success (mocked HTTP)
# ---------------------------------------------------------------------------
print("== (c) chat success ==")


class FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


captured = {}


def fake_urlopen(req, timeout=None):
    captured["url"] = req.full_url
    captured["payload"] = json.loads(req.data.decode())
    return FakeResp({"candidates": [{"content": {"parts": [
        {"text": "Namaste! Kaise ho? Batao, kya khaane ka mood hai?"}]}}]})


with mock.patch.object(brain.urllib.request, "urlopen", fake_urlopen):
    hist = [("user", "hi"), ("model", "Namaste! Main Bhoj House bot hoon.")]
    reply = brain.chat("secret-key", biz, hist, "tum kaise ho", lang="hi")

check(reply and "Namaste" in reply, "chat returns the model text")
check("secret-key" not in captured["url"] or "key=" in captured["url"],
      "key sent as query param")
check("generativelanguage.googleapis.com" in captured["url"],
      "hits the Gemini endpoint")
sys_inst = captured["payload"]["system_instruction"]["parts"][0]["text"]
check(biz["name"] in sys_inst, "system instruction carries business context")
check("Hinglish" in sys_inst, "language hint appended for hi session")
roles = [c["role"] for c in captured["payload"]["contents"]]
check(roles == ["user", "model", "user"], "history roles mapped user/model + new turn")
check(captured["payload"]["contents"][0]["parts"][0]["text"] == "hi",
      "history text passed through")
check(captured["payload"]["generationConfig"]["maxOutputTokens"] <= 400,
      "output capped for WhatsApp-length replies")

# ---------------------------------------------------------------------------
# (d) chat() failure modes -> None
# ---------------------------------------------------------------------------
print("== (d) chat failures ==")


def boom(req, timeout=None):
    raise OSError("no network")


with mock.patch.object(brain.urllib.request, "urlopen", boom):
    check(brain.chat("k", biz, [], "hello") is None,
          "network error -> None (rule fallback takes over)")

with mock.patch.object(brain.urllib.request, "urlopen",
                       lambda req, timeout=None: FakeResp({"error": "bad key"})):
    check(brain.chat("bad", biz, [], "hello") is None,
          "malformed API response -> None")

with mock.patch.object(brain.urllib.request, "urlopen",
                       lambda req, timeout=None: FakeResp({"candidates": []})):
    check(brain.chat("k", biz, [], "hello") is None,
          "empty candidates -> None")

check(brain.chat("", biz, [], "hello") is None, "empty key -> None, no HTTP call")
check(brain.chat("k", biz, [], "   ") is None, "blank text -> None, no HTTP call")

# ---------------------------------------------------------------------------
# (e) storage: encrypted key round-trip
# ---------------------------------------------------------------------------
print("== (e) storage key round-trip ==")
store = Store(":memory:")
u = store.create_user("brain@test.io", "pw")
bid = store.create_business(u, "Brain Café")
store.set_brain_key(bid, "AIza-super-secret")
row = store.get_business(bid)
check(row["brain_api_key_enc"] and "AIza-super-secret" not in row["brain_api_key_enc"],
      "key stored encrypted, never plaintext")
check(store.get_brain_key(bid) == "AIza-super-secret", "key decrypts correctly")
bundle = store.get_business_bundle(bid)
check(bundle["brain_key"] == "" and bundle["brain_enabled"] is False,
      "bundle hides key + disabled flag when brain off")
store.update_business(bid, brain_enabled=1)
bundle = store.get_business_bundle(bid)
check(bundle["brain_enabled"] is True and bundle["brain_key"] == "AIza-super-secret",
      "enabled bundle carries decrypted key for the engine")
store.clear_brain_key(bid)
check(store.get_brain_key(bid) == "", "clear removes the key")
check(store.get_business(bid)["brain_enabled"] == 0, "clear disables the brain")

# ---------------------------------------------------------------------------
# (f) engine: brain answers open chat
# ---------------------------------------------------------------------------
print("== (f) engine brain hook ==")
bb = biz_with_brain()


def fake_brain_chat(api_key, bundle, history, user_text, lang="en"):
    assert api_key == "test-key-123", "engine passes the bundle key"
    assert bundle["name"] == bb["name"], "engine passes the business bundle"
    return "Arre wah, great question! Humari special thali try karo — batao, veg ya non-veg?"


with mock.patch.object(engine._brain, "chat", fake_brain_chat):
    session = {"lang": "hi", "state": "idle", "data": {}}
    replies, new_session = engine.handle_message(
        "919000000101", "aur batao, weekend pe kya special hai?",
        session, business=bb, today=TODAY)
    txt = " ".join(bodies(replies))
    check("Arre wah" in txt, "brain reply used instead of generic fallback")
    check("samajh nahi" not in txt and "didn't quite" not in txt.lower(),
          "generic fallback NOT shown when brain answers")
    ids = []
    for r in replies:
        if r["type"] == "interactive":
            iv = r["interactive"]
            if iv["type"] == "button":
                ids += [b["reply"]["id"] for b in iv["action"]["buttons"]]
    check(any(i.endswith("menu") or i.endswith("book") for i in ids),
          "quick-menu buttons still attached after brain reply")
    hist = new_session.get("hist") or []
    check(len(hist) == 2 and hist[0][0] == "user" and hist[1][0] == "model",
          "exchange recorded in session history")
    check("weekend" in hist[0][1], "user text stored in history")

    # second turn: history is passed back to the brain (conversation kept)
    seen = {}

    def fake_brain_chat2(api_key, bundle, history, user_text, lang="en"):
        seen["n"] = len(history)
        return "Samajh gaya!"

    with mock.patch.object(engine._brain, "chat", fake_brain_chat2):
        replies2, ns2 = engine.handle_message(
            "919000000101", "acha aur kuch interesting batao na", new_session,
            business=bb, today=TODAY)
    check(seen.get("n") == 2, "prior exchange passed as context on next turn")
    check(len(ns2.get("hist") or []) == 4, "history grows across turns")

# ---------------------------------------------------------------------------
# (g) engine: brain failure -> classic fallback, never breaks
# ---------------------------------------------------------------------------
print("== (g) brain failure fallback ==")
with mock.patch.object(engine._brain, "chat", lambda *a, **k: None):
    session = {"lang": "en", "state": "idle", "data": {}}
    replies, ns = engine.handle_message(
        "919000000102", "blorptastic nonsense xyz", session,
        business=bb, today=TODAY)
    txt = " ".join(bodies(replies)).lower()
    check("didn't quite get that" in txt or "samajh" in txt,
          "generic fallback used when brain API fails")
    check("hist" not in ns or not ns["hist"], "no history stored on brain failure")

# ---------------------------------------------------------------------------
# (h) engine: brain off -> untouched classic behaviour
# ---------------------------------------------------------------------------
print("== (h) brain off ==")
plain = biz_with_brain(on=False)
with mock.patch.object(engine._brain, "chat",
                       lambda *a, **k: (_ for _ in ()).throw(
                           AssertionError("brain must not be called"))):
    session = {"lang": "en", "state": "idle", "data": {}}
    replies, _ = engine.handle_message(
        "919000000103", "blorptastic nonsense xyz", session,
        business=plain, today=TODAY)
    txt = " ".join(bodies(replies)).lower()
    check("didn't quite get that" in txt, "classic fallback when brain off")

# ---------------------------------------------------------------------------
# (i) build_bot_system_prompt(): prompt-first bots
# ---------------------------------------------------------------------------
print("== (i) prompt-first system prompt ==")
BOT_NAME = "Chaiwala Bot"
OWNER_PROMPT = ("You are a witty tutor who explains cricket in simple words "
                "and never talks about politics.")
sys_prompt = brain.build_bot_system_prompt(BOT_NAME, OWNER_PROMPT)
check(BOT_NAME in sys_prompt, "bot system prompt names the bot")
check(OWNER_PROMPT in sys_prompt,
      "bot system prompt embeds the owner's prompt text")
check("never reveal" in sys_prompt.lower()
      and "prompt" in sys_prompt.lower(),
      "bot system prompt forbids revealing the prompt")

# ---------------------------------------------------------------------------
# (j) chat_with_prompt(): prompt-first chat (mocked HTTP)
# ---------------------------------------------------------------------------
print("== (j) chat_with_prompt ==")

captured2 = {}


def fake_prompt_urlopen(req, timeout=None):
    captured2["url"] = req.full_url
    captured2["payload"] = json.loads(req.data.decode())
    return FakeResp({"candidates": [{"content": {"parts": [
        {"text": "Hello! I am Chaiwala Bot, at your service."}]}}]})


with mock.patch.object(brain.urllib.request, "urlopen",
                       fake_prompt_urlopen):
    reply = brain.chat_with_prompt("secret-key", BOT_NAME, OWNER_PROMPT,
                                   [], "namaste")

check(reply and "Chaiwala Bot" in reply,
      "chat_with_prompt returns the model text")
sys_inst = captured2["payload"]["system_instruction"]["parts"][0]["text"]
check(OWNER_PROMPT in sys_inst and BOT_NAME in sys_inst,
      "request body system_instruction carries the owner prompt + bot name")


def fake_404_then_ok(req, timeout=None):
    fake_404_then_ok.calls.append(req.full_url)
    if len(fake_404_then_ok.calls) == 1:
        raise urllib.error.HTTPError(
            req.full_url, 404, "Not Found", {},
            io.BytesIO(b'{"error":{"message":"model not found"}}'))
    return FakeResp({"candidates": [{"content": {"parts": [
        {"text": "second model answering"}]}}]})


fake_404_then_ok.calls = []
with mock.patch.object(brain.urllib.request, "urlopen", fake_404_then_ok):
    reply = brain.chat_with_prompt("secret-key", BOT_NAME, OWNER_PROMPT,
                                   [], "hello again")
check(reply == "second model answering"
      and len(fake_404_then_ok.calls) == 2
      and "gemini-2.5-flash" in fake_404_then_ok.calls[1],
      "HTTP 404 on the first model -> retries the second model")


def no_http_allowed(req, timeout=None):
    raise AssertionError("no HTTP call may happen without a key")


with mock.patch.object(brain.urllib.request, "urlopen", no_http_allowed):
    reply = brain.chat_with_prompt("", BOT_NAME, OWNER_PROMPT, [], "hi")
check(reply is not None and "not awake" in reply.lower(),
      "empty key -> honest 'not awake' message, no HTTP call")


def dns_down(req, timeout=None):
    raise urllib.error.URLError("dns down")


with mock.patch.object(brain.urllib.request, "urlopen", dns_down):
    reply = brain.chat_with_prompt("k", BOT_NAME, OWNER_PROMPT, [], "hi")
check(reply is not None and "brain" in reply.lower(),
      "URLError -> honest message mentioning the brain (never None)")

check(brain.chat_with_prompt("k", BOT_NAME, OWNER_PROMPT, [], "   ")
      is not None,
      "chat_with_prompt never returns None (blank text -> honest nudge)")

# ---------------------------------------------------------------------------
# (k) chat_with_prompt_explained(): error codes + owner notes
# ---------------------------------------------------------------------------
print("== (k) chat_with_prompt_explained ==")


def google_400(req, timeout=None):
    raise urllib.error.HTTPError(
        req.full_url, 400, "Bad Request", {},
        io.BytesIO(b'{"error":{"code":400,"message":"API key not valid. '
                   b'Please pass a valid API key.","status":"INVALID_ARGUMENT"}}'))


with mock.patch.object(brain.urllib.request, "urlopen", google_400):
    text, code = brain.chat_with_prompt_explained(
        "bad-key", BOT_NAME, OWNER_PROMPT, [], "hi")
check(code == "bad_key", "HTTP 400 with Google error body -> bad_key")
check("snag reaching my brain" in text,
      "bad key: visitor text stays the honest generic message")
check("bad-key" not in text and "INVALID_ARGUMENT" not in text,
      "no key material or raw Google JSON in the visitor text")


def google_429(req, timeout=None):
    raise urllib.error.HTTPError(
        req.full_url, 429, "Too Many Requests", {},
        io.BytesIO(b'{"error":{"code":429,"message":"Quota exceeded.",'
                   b'"status":"RESOURCE_EXHAUSTED"}}'))


with mock.patch.object(brain.urllib.request, "urlopen", google_429):
    text, code = brain.chat_with_prompt_explained(
        "k", BOT_NAME, OWNER_PROMPT, [], "hi")
check(code == "quota", "HTTP 429 -> quota")


def net_down(req, timeout=None):
    raise urllib.error.URLError("connection refused")


with mock.patch.object(brain.urllib.request, "urlopen", net_down):
    text, code = brain.chat_with_prompt_explained(
        "k", BOT_NAME, OWNER_PROMPT, [], "hi")
check(code == "network", "URLError -> network")
check("couldn't reach my brain" in text.lower(),
      "network failure keeps its honest visitor message")


def all_404(req, timeout=None):
    raise urllib.error.HTTPError(
        req.full_url, 404, "Not Found", {},
        io.BytesIO(b'{"error":{"message":"model not found"}}'))


with mock.patch.object(brain.urllib.request, "urlopen", all_404):
    text, code = brain.chat_with_prompt_explained(
        "k", BOT_NAME, OWNER_PROMPT, [], "hi")
check(code == "models_retired", "all model names 404 -> models_retired")
check("brain models" in text, "models_retired keeps its visitor message")

with mock.patch.object(brain.urllib.request, "urlopen",
                       fake_prompt_urlopen):
    text, code = brain.chat_with_prompt_explained(
        "secret-key", BOT_NAME, OWNER_PROMPT, [], "namaste")
check(code is None and "Chaiwala Bot" in text,
      "success -> (model text, None)")

text, code = brain.chat_with_prompt_explained(
    "", BOT_NAME, OWNER_PROMPT, [], "hi")
check(code == "no_key" and "not awake" in text.lower(),
      "missing key -> no_key with the 'not awake' message")

note = brain.owner_note_for("bad_key")
check("Owner note" in note and "Brain key" in note
      and "bad_key" not in note,
      "owner_note_for(bad_key) is a plain diagnosis, no codes leak")
check(brain.owner_note_for(None) == ""
      and brain.owner_note_for("no_key") == "",
      "success and no_key get no owner note")
check("API key" not in brain.owner_note_for("quota"),
      "owner notes never contain key material")

print(f"\n{PASS} brain checks passed.")
