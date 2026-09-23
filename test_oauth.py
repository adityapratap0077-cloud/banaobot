"""Tests for Google sign-in on the BanaoBot dashboard (/app/*).

Covers:
  - Button hidden when GOOGLE_CLIENT_ID/SECRET are absent; shown when set.
  - /oauth/google redirects to Google's authorization endpoint when enabled,
    and back to login when disabled.
  - Callback rejects Google errors and unverified emails gracefully.
  - Callback find-or-create: new user -> /app/ (bot library); existing
    email -> linked; returning Google user -> dashboard.
  - users.google_sub migration on pre-existing DBs.

Usage: python3 test_oauth.py
Exits non-zero on the first failure. Requires dashboard.py + templates/.
"""

import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("DEMO_MODE", "true")
for var in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"):
    os.environ.pop(var, None)

import dashboard
import server
from storage import Store
from werkzeug.security import check_password_hash

PASS = 0


def check(cond, label):
    global PASS
    if not cond:
        print(f"  FAIL: {label}")
        sys.exit(1)
    PASS += 1
    print(f"  ok: {label}")


print("== real dependency chain (no mocks) ==")
# Calls the true dashboard._google_session (later tests monkeypatch it, so this
# runs first). Catches a repeat of the live incident where authlib was
# installed but its `requests` integration was not.
from dashboard import _google_session as _true_session
os.environ["GOOGLE_CLIENT_ID"] = "x"
os.environ["GOOGLE_CLIENT_SECRET"] = "y"
try:
    _sess = _true_session("https://example.com/cb")
    check(_sess is not None,
          "real _google_session builds with env set (authlib+requests importable)")
finally:
    del os.environ["GOOGLE_CLIENT_ID"]
    del os.environ["GOOGLE_CLIENT_SECRET"]


def fresh_client():
    store = Store(":memory:")
    server.store = store
    server.app.config["store"] = store
    return server.app.test_client(), store


class FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class FakeGoogle:
    """Stands in for authlib's OAuth2Session in the callback tests."""

    def __init__(self, userinfo):
        self._userinfo = userinfo

    def create_authorization_url(self, url, state=None, **kwargs):
        return f"{url}?state={state}", state

    def fetch_token(self, *_a, **_k):
        if self._userinfo is None:
            raise Exception("access_denied")
        return {"access_token": "fake"}

    def get(self, _url):
        return FakeResp(self._userinfo)


def install_fake(userinfo):
    """Route _google_session() at a fake client, bypassing env/network."""
    dashboard._google_session = lambda redirect_uri=None: FakeGoogle(userinfo)
    os.environ["GOOGLE_CLIENT_ID"] = "x"
    os.environ["GOOGLE_CLIENT_SECRET"] = "y"


def uninstall_fake(real_fn):
    dashboard._google_session = real_fn
    os.environ.pop("GOOGLE_CLIENT_ID", None)
    os.environ.pop("GOOGLE_CLIENT_SECRET", None)


def begin_oauth(client):
    """Pass the state check the callback requires."""
    with client.session_transaction() as sess:
        sess["oauth_state"] = "test-state"
    return "/app/oauth/google/callback?code=x&state=test-state"


# ---------------------------------------------------------------- disabled ---

print("== Google sign-in disabled (no env vars) ==")
client, store = fresh_client()

html = client.get("/app/login").get_data(as_text=True)
check("Continue with Google" not in html, "login page hides Google button")

html = client.get("/app/signup").get_data(as_text=True)
check("Sign up with Google" not in html, "signup page hides Google button")

r = client.get("/app/oauth/google")
check(r.status_code == 302 and r.headers["Location"].endswith("/app/login"),
      "/oauth/google redirects to login when disabled")

r = client.get("/app/oauth/google/callback")
check(r.status_code == 302 and r.headers["Location"].endswith("/app/login"),
      "/oauth/google/callback redirects to login when disabled")

# ------------------------------------------------------------ button shown ---

print("== Google sign-in enabled (env vars set) ==")
os.environ["GOOGLE_CLIENT_ID"] = "test-client-id.apps.googleusercontent.com"
os.environ["GOOGLE_CLIENT_SECRET"] = "test-secret"
client, store = fresh_client()

html = client.get("/app/login").get_data(as_text=True)
check("Continue with Google" in html and "/app/oauth/google" in html,
      "login page shows Google button linking to /app/oauth/google")

html = client.get("/app/signup").get_data(as_text=True)
check("Sign up with Google" in html,
      "signup page shows Google button")

r = client.get("/app/oauth/google")
loc = r.headers.get("Location", "")
check(r.status_code == 302
      and loc.startswith("https://accounts.google.com/o/oauth2/"),
      "/oauth/google redirects to Google authorization endpoint")
check("client_id=test-client-id.apps.googleusercontent.com" in loc,
      "authorization URL carries the client id")
check("oauth%2Fgoogle%2Fcallback" in loc or "oauth/google/callback" in loc,
      "authorization URL carries the /app/oauth/google/callback redirect URI")

# ------------------------------------------------------- callback: errors -----

print("== callback: Google-side errors ==")
r = client.get("/app/oauth/google/callback?error=access_denied")
check(r.status_code == 302 and r.headers["Location"].endswith("/app/login"),
      "callback with error=access_denied redirects to login")
r = client.get("/app/oauth/google/callback?code=x&state=bogus")
check(r.status_code == 302 and r.headers["Location"].endswith("/app/login"),
      "callback with wrong state is rejected (CSRF)")
r = client.get("/app/oauth/google/callback?state=bogus")
check(r.status_code == 302 and r.headers["Location"].endswith("/app/login"),
      "callback without a code is rejected")

# --------------------------------------------------- callback: full flows -----

print("== callback: find-or-create flows ==")
real_fn = dashboard._google_session

# 1. brand-new Google user -> account created -> /app/ (bot library)
install_fake({"sub": "g-111", "email": "New@Example.com",
              "email_verified": True, "name": "New Person"})
client, store = fresh_client()
install_fake({"sub": "g-111", "email": "New@Example.com",
              "email_verified": True, "name": "New Person"})
r = client.get(begin_oauth(client))
check(r.status_code == 302 and r.headers["Location"].endswith("/app/"),
      "new Google user is created and lands on /app/ (bot library)")
user = store.get_user_by_google_sub("g-111")
check(user is not None and user["email"] == "new@example.com",
      "new user row stored with google_sub + lowercased email")
check(not check_password_hash(user["password_hash"], "anything"),
      "Google-only account has an unusable password hash")
with client.session_transaction() as sess:
    check(sess.get("user_id") == user["id"], "new user is logged in")

# 2. same Google account again -> dashboard, no duplicate row
r = client.get(begin_oauth(client))
check(r.status_code == 302 and r.headers["Location"].endswith("/app/"),
      "returning Google user lands on the dashboard")
n = store._conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
check(n == 1, "no duplicate user row on second Google login")

# 3. existing email/password user links their Google account
uid = store.create_user("owner@shop.com",
                        "pbkdf2:sha256:1$abc$def")  # placeholder hash
install_fake({"sub": "g-222", "email": "owner@shop.com",
              "email_verified": True})
r = client.get(begin_oauth(client))
check(r.status_code == 302 and r.headers["Location"].endswith("/app/"),
      "existing email user is logged in via Google")
linked = store.get_user(uid)
check(linked["google_sub"] == "g-222",
      "google_sub is linked onto the existing account")

# 4. unverified email is rejected
install_fake({"sub": "g-333", "email": "evil@example.com",
              "email_verified": False})
r = client.get(begin_oauth(client))
check(r.status_code == 302 and r.headers["Location"].endswith("/app/login"),
      "unverified Google email is rejected")
check(store.get_user_by_google_sub("g-333") is None,
      "no user row created for unverified email")

# 5. Google-side token failure mid-callback
install_fake(None)
r = client.get(begin_oauth(client))
check(r.status_code == 302 and r.headers["Location"].endswith("/app/login"),
      "token exchange failure redirects to login")

uninstall_fake(real_fn)

# ------------------------------------------------------------- migration -----

print("== users.google_sub migration on old DBs ==")
path = "/tmp/banaobot_old_users.db"
if os.path.exists(path):
    os.remove(path)
conn = sqlite3.connect(path)
conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT,"
             " email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,"
             " created_at INTEGER NOT NULL)")
conn.execute("INSERT INTO users (email, password_hash, created_at)"
             " VALUES ('old@example.com', 'h', 1)")
conn.commit()
conn.close()
st = Store(path)
cols = [r[1] for r in st._conn.execute("PRAGMA table_info(users)").fetchall()]
check("google_sub" in cols, "old DB gains google_sub column on open")
check(st.get_user_by_email("old@example.com")["email"] == "old@example.com",
      "old rows still readable after migration")
os.remove(path)

print(f"\nALL {PASS} OAUTH CHECKS PASSED ✔")
