"""Tests for the build-from-website feature (sitefetch.py + wiring).

Covers:
  extract_brief on a cafe fixture (name, offerings, price, hours, phone;
    nav/footer/header noise ignored)
  detect_theme (meta theme-color wins; else most frequent non-gray hex;
    None when nothing usable)
  build_prompt_from_brief (name + offering present; thin brief gets an
    honesty note and no invented prices)
  fetch_site (rejects ftp://, private/loopback/link-local IPs, embedded
    credentials, non-200, non-HTML, and redirects to private IPs)
  POST /app/fetch-site (login required, bad URL -> ok:false, success with
    mocked fetch_site, 10/hour rate limit)
  public chat theming (/b/<token> and ?embed=1: valid color rendered,
    invalid falls back to default orange)
  website columns persist through create/get/update (+ migration of an
    old-schema DB)

Usage: python3 test_sitefetch.py
Exits non-zero on the first failure.
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("DEMO_MODE", "true")

import sitefetch
import server
import dashboard
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
    store = Store(":memory:")
    server.store = store
    server.app.config["store"] = store
    return server.app.test_client(), store


CAFE_HTML = """<!doctype html><html><head>
<title>Brew &amp; Bean Caf\u00e9</title>
<meta name="description" content="A cozy neighbourhood caf\u00e9 for slow mornings.">
<meta property="og:site_name" content="Brew &amp; Bean Caf\u00e9">
<meta name="theme-color" content="#7a4a21">
<link rel="icon" href="/favicon.ico">
</head><body>
<nav><a href="#">Home</a><a href="#">Secret deal \u20b9999</a></nav>
<header><p>Call now for catering!</p></header>
<h1>Welcome to Brew &amp; Bean</h1>
<p>We are a cozy neighbourhood caf\u00e9 pouring slow mornings and strong
filter coffee since 2019. Come as you are!</p>
<h2>Menu</h2>
<ul>
<li>Masala chai \u2014 \u20b930</li>
<li>Filter coffee \u2014 \u20b950</li>
<li>Bun maska \u2014 \u20b940</li>
</ul>
<p>Open daily 8 AM \u2013 10 PM. Kitchen closes at 9:30 PM.</p>
<p>Call us at +91 98765 43210 or write to hello@brewandbean.example</p>
<footer><p>\u00a9 2026 Brew &amp; Bean</p></footer>
</body></html>"""

URL = "https://brewandbean.example/"

# ------------------------------------------------- 1. extract_brief
print("== (1) extract_brief ==")
brief = sitefetch.extract_brief(CAFE_HTML, URL)
check(brief["name"] == "Brew & Bean Caf\u00e9",
      "name prefers og:site_name")
check("cozy neighbourhood" in brief["tagline"],
      "tagline from meta description")
check("slow mornings" in brief["description"],
      "description from substantial paragraphs")
check(any("Masala chai" in o for o in brief["offerings"]),
      "offerings include a menu item")
check(len(brief["offerings"]) <= 20, "offerings capped at ~20")
check(any("\u20b930" in p for p in brief["prices"]),
      "prices catch the \u20b930 fragment")
check(not any("\u20b9999" in p for p in brief["prices"]),
      "nav noise (\u20b9999) is ignored")
check(any("8 AM" in h for h in brief["hours"]),
      "hours catch the opening-times fragment")
check(any("98765 43210" in c for c in brief["contact"]),
      "contact catches the phone number")
check(any("hello@brewandbean.example" in c for c in brief["contact"]),
      "contact catches the email")
check(isinstance(brief["tone"], str) and brief["tone"]
      and "No readable text" not in brief["tone"],
      "tone is a one-line heuristic")

# ------------------------------------------------- 2. detect_theme
print("== (2) detect_theme ==")
theme = sitefetch.detect_theme(CAFE_HTML, URL)
check(theme["primary"] == "#7a4a21",
      "meta theme-color wins")
check(theme["logo"] == "https://brewandbean.example/favicon.ico",
      "logo resolves favicon to an absolute URL")

no_meta = ("<html><head><title>X</title></head><body>"
           "<style>.btn{background:#e85d26}.btn:hover{background:#e85d26}"
           "p{color:#333}</style>"
           '<div style="border-color:#e85d26">hi</div></body></html>')
theme2 = sitefetch.detect_theme(no_meta, URL)
check(theme2["primary"] == "#e85d26",
      "most frequent non-gray hex wins when no meta theme-color")

gray_only = ("<html><head></head><body>"
             "<style>p{color:#333}div{background:#ffffff}</style>"
             "</body></html>")
theme3 = sitefetch.detect_theme(gray_only, URL)
check(theme3["primary"] is None,
      "grays/black/white-only pages yield None")
check(theme3["logo"] is None, "no logo when none is declared")

check(sitefetch.normalize_theme_hex("#ABCDEF") == "#abcdef",
      "normalize lowercases a valid hex")
check(sitefetch.normalize_theme_hex("#abc") is None,
      "normalize rejects 3-digit hex")
check(sitefetch.normalize_theme_hex("red") is None,
      "normalize rejects color names")
check(sitefetch.normalize_theme_hex("#12345g") is None,
      "normalize rejects non-hex digits")

# ------------------------------------------------- 3. build_prompt_from_brief
print("== (3) build_prompt_from_brief ==")
prompt = sitefetch.build_prompt_from_brief(brief, URL)
check("Brew & Bean Caf\u00e9" in prompt, "prompt contains the business name")
check("Masala chai" in prompt, "prompt contains an offering")
check("\u20b930" in prompt, "prompt contains a real price from the site")
check("never invent" in prompt.lower(), "prompt has a no-invention rule")
check(len(prompt) > 20, "generated prompt clears the 20-char minimum")

thin = {"name": "Mystery Co", "tagline": "", "description": "",
        "offerings": [], "prices": [], "hours": [], "contact": [],
        "tone": "No readable text to judge tone from."}
thin_prompt = sitefetch.build_prompt_from_brief(thin, "https://thin.example")
check("honest" in thin_prompt.lower(),
      "thin brief gets an honesty note")
check(not any(c in thin_prompt for c in ("\u20b9", "$", "\u20ac", "\u00a3"))
      and "Rs." not in thin_prompt,
      "thin brief invents no prices")

# ------------------------------------------------- 4. fetch_site guards
print("== (4) fetch_site guards ==")


def raises_sitefetch(fn, label, needle=""):
    try:
        fn()
    except sitefetch.SiteFetchError as exc:
        check(not needle or needle.lower() in str(exc).lower(),
              label + f" (message: {exc})")
        return
    except Exception as exc:  # noqa: BLE001 - any other error is a failure
        print(f"  FAIL: {label} (leaked {type(exc).__name__}: {exc})")
        sys.exit(1)
    print(f"  FAIL: {label} (no error raised)")
    sys.exit(1)


raises_sitefetch(lambda: sitefetch.fetch_site("ftp://example.com/file"),
                 "rejects ftp:// URLs", "http")
raises_sitefetch(lambda: sitefetch.fetch_site("file:///etc/passwd"),
                 "rejects file:// URLs", "http")
raises_sitefetch(lambda: sitefetch.fetch_site(
    "http://user:pass@example.com/"),
    "rejects URLs with embedded credentials", "username")
raises_sitefetch(lambda: sitefetch.fetch_site("http://127.0.0.1/"),
                 "rejects loopback IP (SSRF)", "private")
raises_sitefetch(lambda: sitefetch.fetch_site("http://169.254.169.254/"),
                 "rejects link-local IP (SSRF)", "private")
raises_sitefetch(lambda: sitefetch.fetch_site("http://10.0.0.5/"),
                 "rejects private 10/8 IP (SSRF)", "private")
raises_sitefetch(lambda: sitefetch.fetch_site("127.0.0.1"),
                 "bare IP without scheme still SSRF-checked", "private")


class _FakeResp:
    def __init__(self, status=200, headers=None):
        self.status_code = status
        self.headers = headers or {}
        self.encoding = "utf-8"

    def close(self):
        pass

    def iter_content(self, chunk_size=65536):
        yield b"<html><body>hi</body></html>"


_real_get = sitefetch.requests.get


def _patch_get(resp):
    sitefetch.requests.get = lambda *a, **k: resp


try:
    _patch_get(_FakeResp(404, {"Content-Type": "text/html"}))
    raises_sitefetch(lambda: sitefetch.fetch_site("http://8.8.8.8/missing"),
                     "non-200 status -> honest error", "status 404")
    _patch_get(_FakeResp(200, {"Content-Type": "application/pdf"}))
    raises_sitefetch(lambda: sitefetch.fetch_site("http://8.8.8.8/file.pdf"),
                     "non-HTML content -> honest error", "html")
    _patch_get(_FakeResp(301, {"Location": "http://127.0.0.1/blocked"}))
    raises_sitefetch(lambda: sitefetch.fetch_site("http://8.8.8.8/"),
                     "redirect to private IP is SSRF-blocked", "private")
finally:
    sitefetch.requests.get = _real_get

# ------------------------------------------------- 5. /app/fetch-site endpoint
print("== (5) /app/fetch-site endpoint ==")
client, store = fresh_client()
dashboard._site_fetch_hits.clear()

r = client.post("/app/fetch-site", json={"url": "https://x.example"})
check(r.status_code == 302 and r.headers["Location"].endswith("/app/login"),
      "anonymous POST redirects to /app/login")

EMAIL, PW = "fetch@test.local", "secret123"
r = client.post("/app/signup",
                data={"email": EMAIL, "password": PW, "confirm": PW})
check(r.status_code == 302, "signup works for the fetch test user")

r = client.post("/app/fetch-site", json={"url": "ftp://example.com/x"})
data = r.get_json()
check(r.status_code == 400 and data["ok"] is False and data["error"],
      "bad URL -> ok:false with a message")

r = client.post("/app/fetch-site", json={"url": ""})
data = r.get_json()
check(data["ok"] is False, "empty URL -> ok:false")

real_fetch = sitefetch.fetch_site
sitefetch.fetch_site = lambda url: (CAFE_HTML, "https://brewandbean.example/")
try:
    r = client.post("/app/fetch-site",
                    json={"url": "brewandbean.example"})
    data = r.get_json()
    check(r.status_code == 200 and data["ok"] is True,
          "mocked fetch -> ok:true")
    check(data["name"] == "Brew & Bean Caf\u00e9",
          "response carries the detected name")
    check(len(data["prompt"]) > 20 and "Masala chai" in data["prompt"],
          "response carries a generated prompt")
    check(data["theme_color"] == "#7a4a21",
          "response carries the detected theme color")
    check(data["url"] == "https://brewandbean.example/",
          "response carries the final URL")
finally:
    sitefetch.fetch_site = real_fetch

# new-bot page renders the website-import block above the manual form
r = client.get("/app/bots/new")
html = r.get_data(as_text=True)
check("Build from your website" in html and 'id="site-url"' in html,
      "new-bot page shows the website-import block")
check('name="website_url"' in html and 'name="theme_color"' in html,
      "new-bot form carries website hidden fields")
check(html.index("Build from your website") < html.index('id="prompt"'),
      "website block sits above the manual prompt form")

# rate limit: 10/hour per user
dashboard._site_fetch_hits.clear()
sitefetch.fetch_site = lambda url: (CAFE_HTML, "https://brewandbean.example/")
try:
    for i in range(10):
        r = client.post("/app/fetch-site",
                        json={"url": "https://x%d.example" % i})
        check(r.get_json()["ok"] is True, f"fetch {i + 1}/10 allowed")
    r = client.post("/app/fetch-site", json={"url": "https://x11.example"})
    data = r.get_json()
    check(r.status_code == 429 and data["ok"] is False,
          "11th fetch within an hour -> 429 ok:false")
finally:
    sitefetch.fetch_site = real_fetch
    dashboard._site_fetch_hits.clear()

# creating a bot with website fields persists them
r = client.post("/app/bots/new", data={
    "name": "Brew Bot",
    "prompt": "You are the host of Brew & Bean Caf\u00e9, a cozy place.",
    "website_url": "https://brewandbean.example/",
    "theme_color": "#7a4a21",
})
m = re.search(r"/app/bots/(\d+)$", r.headers.get("Location", ""))
check(r.status_code == 302 and m, "create bot with website fields -> 302")
bid = int(m.group(1))
bot = store.get_bot(bid)
check(bot["website_url"] == "https://brewandbean.example/",
      "website_url persisted on create")
check(bot["theme_color"] == "#7a4a21", "theme_color persisted on create")

# bot detail page shows the source + swatch (read-only)
r = client.get(f"/app/bots/{bid}")
html = r.get_data(as_text=True)
check("Built from" in html and "https://brewandbean.example/" in html,
      "detail page shows the source website")
check("#7a4a21" in html, "detail page shows the theme swatch")

# ------------------------------------------------- 6. public chat theming
print("== (6) public chat theming ==")
uid = store.create_user("theme@test.local", "hash")
LONG_PROMPT = ("You are a test bot. " * 10).strip()
tbid = store.create_bot(uid, "Themed Bot", LONG_PROMPT,
                        theme_color="#123abc")
token = store.get_bot(tbid)["share_token"]

r = client.get(f"/b/{token}")
html = r.get_data(as_text=True)
check(r.status_code == 200 and "#123abc" in html,
      "/b/<token> renders the bot's theme color")

r = client.get(f"/b/{token}?embed=1")
html = r.get_data(as_text=True)
check(r.status_code == 200 and "#123abc" in html,
      "?embed=1 renders the bot's theme color")

# invalid theme_color -> falls back to default orange, never injected raw
store._conn.execute("UPDATE bots SET theme_color=? WHERE id=?",
                     ("not-a-color\"><script>", tbid))
store._conn.commit()
r = client.get(f"/b/{token}")
html = r.get_data(as_text=True)
check("not-a-color" not in html, "invalid theme color is never injected")
check("#e85d26" in html, "invalid theme color falls back to default orange")

plain = store.create_bot(uid, "Plain Bot", LONG_PROMPT)
ptoken = store.get_bot(plain)["share_token"]
r = client.get(f"/b/{ptoken}")
check("#e85d26" in r.get_data(as_text=True),
      "bot without a theme uses the default orange")

# ------------------------------------------------- 7. website columns persist
print("== (7) website columns persist ==")
cbid = store.create_bot(uid, "Cols Bot", LONG_PROMPT,
                        website_url="https://a.example",
                        theme_color="#A1B2C3")
bot = store.get_bot(cbid)
check(bot["website_url"] == "https://a.example",
      "create_bot stores website_url")
check(bot["theme_color"] == "#a1b2c3",
      "create_bot normalizes theme_color to lowercase hex")
check(any(b["id"] == cbid and b["website_url"] == "https://a.example"
          for b in store.list_bots(uid)),
      "list_bots returns website columns")

check(store.update_bot(cbid, uid, website_url="https://b.example",
                       theme_color="#d4e5f6") is True,
      "update_bot accepts website fields")
bot = store.get_bot(cbid)
check(bot["website_url"] == "https://b.example"
      and bot["theme_color"] == "#d4e5f6",
      "update_bot persists website fields")
check(store.update_bot(cbid, uid, theme_color="bogus") is True,
      "update_bot accepts an invalid theme without crashing")
check(store.get_bot(cbid)["theme_color"] is None,
      "invalid theme_color is stored as None, not raw text")
check(store.update_bot(cbid, uid, name="Cols Bot") is True,
      "update_bot without website fields leaves them untouched")
check(store.get_bot(cbid)["website_url"] == "https://b.example",
      "website_url untouched when not passed")

# ------------------------------------------------- 8. migration of an old DB
print("== (8) migration of pre-feature DBs ==")
import sqlite3
import tempfile

fd, old_path = tempfile.mkstemp(suffix=".db")
os.close(fd)
os.unlink(old_path)
conn = sqlite3.connect(old_path)
conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, "
             "email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, "
             "created_at INTEGER NOT NULL)")
conn.execute("CREATE TABLE bots (id INTEGER PRIMARY KEY AUTOINCREMENT, "
             "user_id INTEGER NOT NULL, name TEXT NOT NULL, "
             "prompt TEXT NOT NULL, share_token TEXT UNIQUE NOT NULL, "
             "created_at INTEGER NOT NULL)")
conn.commit()
conn.close()
old_store = Store(old_path)
cols = {r["name"] for r in
        old_store._conn.execute("PRAGMA table_info(bots)")}
check("website_url" in cols and "theme_color" in cols,
      "old DB gains website_url/theme_color via ALTER TABLE")
muid = old_store.create_user("mig@test.local", "hash")
mbid = old_store.create_bot(muid, "Mig Bot", LONG_PROMPT,
                            website_url="https://old.example",
                            theme_color="#a1b2c3")
mbot = old_store.get_bot(mbid)
check(mbot["website_url"] == "https://old.example"
      and mbot["theme_color"] == "#a1b2c3",
      "migrated DB stores website fields on new bots")
os.unlink(old_path)

print(f"\nALL {PASS} SITEFETCH CHECKS PASSED ✔")
