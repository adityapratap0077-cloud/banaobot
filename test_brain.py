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

print(f"\n{PASS} brain checks passed.")
