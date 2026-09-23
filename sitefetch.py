"""Build-from-website: fetch a business site, extract a brief, detect theme.

Stdlib only for parsing/extraction (html.parser, ipaddress, socket, re);
HTTP is done with ``requests``, which is already a project dependency —
nothing new is added to requirements.txt.

Public API:
  fetch_site(url)              -> (html, final_url); raises SiteFetchError
  extract_brief(html, url)      -> dict of business facts
  detect_theme(html, url)       -> {"primary": "#rrggbb"|None, "logo": url|None}
  build_prompt_from_brief(brief, url) -> natural-language bot prompt
  normalize_theme_hex(value)   -> "#rrggbb" or None (strict)

Security notes:
  * Only http/https URLs are accepted; embedded credentials are rejected.
  * Every hop (initial URL + each redirect target) is resolved with
    socket.getaddrinfo and rejected when it points at a private, loopback,
    link-local, multicast, reserved, or unspecified address (SSRF guard).
  * Bodies are capped at ~2MB, redirects at 5, timeout at 10s.
  * SiteFetchError messages are written for end users — safe to show in UI.
"""

import ipaddress
import re
import socket
from html.parser import HTMLParser
from urllib.parse import urlsplit, urlunsplit, urljoin

import requests

MAX_BYTES = 2 * 1024 * 1024
FETCH_TIMEOUT = 10
MAX_REDIRECTS = 5
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0.0 Safari/537.36")


class SiteFetchError(Exception):
    """Human-friendly fetch failure. str(exc) is safe to show in the UI."""


# ---------------------------------------------------------------------------
# URL validation + SSRF guard
# ---------------------------------------------------------------------------

def _clean_url(url):
    """Normalize a user-supplied URL or raise SiteFetchError."""
    url = (url or "").strip()
    if not url:
        raise SiteFetchError("Paste your website address first.")
    if "://" not in url:
        # Friendly: "brewandbean.com" -> "https://brewandbean.com"
        url = "https://" + url
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise SiteFetchError(
            "That doesn't look like a web address — paste a link starting "
            "with http:// or https://.")
    if parts.username or parts.password:
        raise SiteFetchError(
            "Links with a username or password in them aren't accepted — "
            "paste the plain address instead.")
    host = (parts.hostname or "").strip().lower().rstrip(".")
    if not host:
        raise SiteFetchError(
            "That address is missing a website name — check it and try again.")
    netloc = host
    if parts.port:
        netloc = "%s:%d" % (host, parts.port)
    return urlunsplit((parts.scheme, netloc, parts.path or "/",
                       parts.query, ""))


def _assert_public_host(host, port):
    """Reject hostnames that resolve to non-public IPs (SSRF guard)."""
    try:
        infos = socket.getaddrinfo(host, port or 443,
                                   type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise SiteFetchError(
            "Couldn't reach that website — check the address and try again.")
    except Exception:
        raise SiteFetchError(
            "Couldn't reach that website — check the address and try again.")
    if not infos:
        raise SiteFetchError(
            "Couldn't reach that website — check the address and try again.")
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            raise SiteFetchError(
                "Couldn't reach that website — check the address and try "
                "again.")
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_multicast or ip.is_reserved or ip.is_unspecified):
            raise SiteFetchError(
                "That address points to a private or internal network, so "
                "it can't be fetched. Use your public website address.")


def fetch_site(url):
    """GET a page safely. Returns (html, final_url).

    Raises SiteFetchError with a UI-safe message on any problem: bad URL,
    blocked address, DNS failure, non-200 status, non-HTML content, too
    many redirects, or a dropped connection.
    """
    current = _clean_url(url)
    for _ in range(MAX_REDIRECTS + 1):
        parts = urlsplit(current)
        _assert_public_host(parts.hostname, parts.port)
        try:
            resp = requests.get(current, timeout=FETCH_TIMEOUT,
                                headers={"User-Agent": USER_AGENT},
                                stream=True, allow_redirects=False)
        except requests.RequestException:
            raise SiteFetchError(
                "Couldn't reach that website — it may be down or blocking "
                "automated visits. Check the address and try again.")
        if resp.status_code in (301, 302, 303, 307, 308):
            location = resp.headers.get("Location")
            resp.close()
            if not location:
                raise SiteFetchError(
                    "That link didn't lead anywhere (broken redirect).")
            current = urljoin(current, location)
            hop = urlsplit(current)
            if hop.scheme not in ("http", "https"):
                raise SiteFetchError(
                    "That link redirected somewhere that isn't a web page.")
            if hop.username or hop.password:
                raise SiteFetchError(
                    "Links with a username or password in them aren't "
                    "accepted — paste the plain address instead.")
            continue
        if resp.status_code != 200:
            resp.close()
            raise SiteFetchError(
                "That link didn't return a readable page "
                "(status %d)." % resp.status_code)
        ctype = resp.headers.get("Content-Type", "")
        if "text/html" not in ctype.lower():
            resp.close()
            raise SiteFetchError(
                "That link didn't return a readable web page — it wasn't "
                "HTML.")
        chunks = []
        size = 0
        try:
            for chunk in resp.iter_content(65536):
                if not chunk:
                    continue
                size += len(chunk)
                if size > MAX_BYTES:
                    break
                chunks.append(chunk)
        except requests.RequestException:
            raise SiteFetchError(
                "The connection dropped while reading that page — "
                "try again.")
        finally:
            resp.close()
        raw = b"".join(chunks)
        charset = resp.encoding or "utf-8"
        try:
            html = raw.decode(charset, errors="replace")
        except (LookupError, ValueError):
            html = raw.decode("utf-8", errors="replace")
        return html, current
    raise SiteFetchError("That link redirected too many times.")


# ---------------------------------------------------------------------------
# HTML parsing (stdlib html.parser)
# ---------------------------------------------------------------------------

class _BriefHTMLParser(HTMLParser):
    """Collects title, meta, headings, paragraphs, list items, style info.

    Skips <nav>, <header>, <footer>, <aside>, <script>, <style> (content),
    <noscript> subtrees so menus and chrome don't pollute the brief.
    """

    SKIP = {"script", "style", "nav", "footer", "header", "noscript", "aside"}
    TEXT_TAGS = {"h1": "h", "h2": "h", "h3": "h", "h4": "h",
                 "h5": "h", "h6": "h", "p": "p", "li": "li"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title_parts = []
        self._in_title = False
        self.meta = {}
        self.headings = []
        self.paragraphs = []
        self.items = []
        self.style_css = []
        self.inline_styles = []
        self.favicons = []
        self._buf = None
        self._buf_kind = None
        self._buf_cap = 0
        self._skip_depth = 0
        self._in_style_block = False
        self._style_buf = []

    def _start_buf(self, kind, cap):
        self._buf_kind = kind
        self._buf_cap = cap
        self._buf = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in self.SKIP:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "title":
            self._in_title = True
        elif tag == "meta":
            key = (a.get("property") or a.get("name") or "").lower().strip()
            content = a.get("content", "").strip()
            if key and content and key not in self.meta:
                self.meta[key] = content
        elif tag == "link":
            rel = a.get("rel", "").lower()
            href = a.get("href", "").strip()
            if href and "icon" in rel:
                self.favicons.append(href)
        elif tag == "style":
            self._in_style_block = True
            self._style_buf = []
        elif tag in self.TEXT_TAGS:
            self._start_buf(self.TEXT_TAGS[tag],
                             2000 if tag == "p" else 200)
        if a.get("style"):
            self.inline_styles.append(a["style"])

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in self.SKIP:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return
        if tag == "title":
            self._in_title = False
        elif tag == "style" and self._in_style_block:
            self._in_style_block = False
            self.style_css.append("".join(self._style_buf))
            self._style_buf = []
        elif tag in self.TEXT_TAGS and self._buf is not None:
            text = re.sub(r"\s+", " ", "".join(self._buf)).strip()
            if text:
                if self._buf_kind == "h":
                    self.headings.append(text[:160])
                elif self._buf_kind == "p":
                    self.paragraphs.append(text[:2000])
                else:
                    self.items.append(text[:200])
            self._buf = None
            self._buf_kind = None

    def handle_data(self, data):
        if self._skip_depth:
            return
        if self._in_title:
            self.title_parts.append(data)
        elif self._in_style_block:
            self._style_buf.append(data)
        elif self._buf is not None:
            if len("".join(self._buf)) < self._buf_cap:
                self._buf.append(data)


def _parse(html):
    parser = _BriefHTMLParser()
    try:
        parser.feed(html or "")
        parser.close()
    except Exception:
        pass  # best effort: return whatever was collected
    return parser


# ---------------------------------------------------------------------------
# Brief extraction
# ---------------------------------------------------------------------------

PRICE_RE = re.compile(r"(₹|Rs\.?|INR|\$|€|£)\s*[\d,]+(?:\.\d{1,2})?")
TIME_RE = re.compile(r"\d{1,2}(:\d{2})?\s*(am|pm)\b|\b\d{1,2}:\d{2}\b", re.I)
HOURS_HINT_RE = re.compile(
    r"\b(open|opening|hours?|timings?|mon(day)?|tue(sday)?|wed(nesday)?|"
    r"thu(rsday)?|fri(day)?|sat(urday)?|sun(day)?)\b", re.I)
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE_RE = re.compile(r"\+?\d[\d\s\-().]{6,}\d")
ADDRESS_HINT_RE = re.compile(
    r"\b(address|located at|find us|visit us|reach us)\b.{0,90}", re.I)


def _dedupe(items, cap):
    seen = set()
    out = []
    for item in items:
        key = item.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item.strip())
        if len(out) >= cap:
            break
    return out


def _fragments_with(parser, predicate, cap, maxlen=140):
    found = []
    for text in parser.headings + parser.items + parser.paragraphs:
        if predicate(text):
            found.append(text[:maxlen])
    return _dedupe(found, cap)


def _contacts(parser):
    found = []
    for text in parser.headings + parser.items + parser.paragraphs:
        for m in EMAIL_RE.finditer(text):
            found.append(m.group(0))
        for m in PHONE_RE.finditer(text):
            num = re.sub(r"\s+", " ", m.group(0)).strip()
            digits = re.sub(r"\D", "", num)
            # Skip price look-alikes and implausibly long digit runs.
            if "₹" in text[max(0, m.start() - 3):m.end()] or \
                    "$" in text[max(0, m.start() - 3):m.end()]:
                continue
            if 7 <= len(digits) <= 15:
                found.append(num)
        for m in ADDRESS_HINT_RE.finditer(text):
            found.append(m.group(0).strip())
    return _dedupe(found, 5)


def _tone(paragraphs, headings):
    text = " ".join(paragraphs + headings)
    words = re.findall(r"[a-zA-Z']+", text.lower())
    if not words:
        return "No readable text to judge tone from."
    sentences = [s for s in re.split(r"[.!?]+", text) if s.strip()]
    avg = (sum(len(s.split()) for s in sentences) / len(sentences)
           if sentences else 0)
    playful_hits = sum(1 for w in words if w in {
        "love", "loved", "delicious", "yummy", "fun", "welcome", "cozy",
        "fresh", "happy", "tasty", "awesome", "amazing", "cute"}) \
        + text.count("!")
    formal_hits = sum(1 for w in words if w in {
        "established", "services", "solutions", "enterprise", "mission",
        "vision", "certified", "provider", "facilitate", "leverage",
        "synergy", "pursuant", "hereby"})
    if playful_hits > formal_hits and avg < 18:
        return "Playful and welcoming — short, warm sentences."
    if formal_hits >= playful_hits and avg >= 18:
        return "Formal and wordy — reads like a company brochure."
    if playful_hits >= formal_hits:
        return "Friendly and casual — easy to read."
    return "Neutral and informative."


def extract_brief(html, url):
    """Extract a business brief from page HTML.

    Returns a dict: name, tagline, description, offerings, prices, hours,
    contact, tone. Missing pieces are empty strings/lists — never guessed.
    """
    parser = _parse(html)
    meta = parser.meta
    host = urlsplit(url or "").hostname or ""

    title = re.sub(r"\s+", " ", "".join(parser.title_parts)).strip()
    if not meta.get("og:site_name") and title:
        for sep in (" | ", " — ", " – ", " - ", " :: ", " · "):
            if sep in title:
                title = title.split(sep)[0].strip()
                break
    name = meta.get("og:site_name") or title or host

    tagline = meta.get("description") or meta.get("og:description") or ""

    desc_paras = [p for p in parser.paragraphs if len(p) >= 40][:3]
    description = "\n\n".join(desc_paras)[:900]

    offerings = _dedupe(
        [h for h in parser.headings if 3 <= len(h) <= 80] +
        [i for i in parser.items if 3 <= len(i) <= 120], 20)

    prices = _fragments_with(parser, lambda t: bool(PRICE_RE.search(t)), 10)
    hours = _fragments_with(
        parser,
        lambda t: bool(HOURS_HINT_RE.search(t) and TIME_RE.search(t)), 5)
    contact = _contacts(parser)

    return {
        "name": name.strip(),
        "tagline": tagline.strip(),
        "description": description.strip(),
        "offerings": offerings,
        "prices": prices,
        "hours": hours,
        "contact": contact,
        "tone": _tone(parser.paragraphs, parser.headings),
    }


# ---------------------------------------------------------------------------
# Theme detection
# ---------------------------------------------------------------------------

HEX_RE = re.compile(r"#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})\b")


def normalize_theme_hex(value):
    """Strictly validate a theme color. Returns "#rrggbb" or None."""
    m = re.fullmatch(r"#([0-9a-fA-F]{6})", (value or "").strip())
    return ("#" + m.group(1).lower()) if m else None


def _expand_hex(short):
    short = short.lower()
    if len(short) == 3:
        return "#" + "".join(c * 2 for c in short)
    return "#" + short


def _is_grayish(hex6):
    r, g, b = int(hex6[1:3], 16), int(hex6[3:5], 16), int(hex6[5:7], 16)
    return max(r, g, b) - min(r, g, b) <= 24


def detect_theme(html, url):
    """Detect the site's brand color and logo.

    Returns {"primary": "#rrggbb"|None, "logo": absolute_url|None}.
    Prefers <meta name="theme-color">; otherwise the most frequent
    non-gray hex color found in <style> blocks and style attributes.
    """
    parser = _parse(html)
    primary = normalize_theme_hex(parser.meta.get("theme-color", ""))
    if not primary:
        counts = {}
        for css in parser.style_css + parser.inline_styles:
            for m in HEX_RE.finditer(css):
                hex6 = _expand_hex(m.group(1))
                if _is_grayish(hex6):
                    continue
                counts[hex6] = counts.get(hex6, 0) + 1
        if counts:
            primary = max(counts, key=lambda h: (counts[h], h))
    logo = parser.meta.get("og:image") or \
        (parser.favicons[0] if parser.favicons else None)
    if logo:
        logo = urljoin(url or "", logo)
    return {"primary": primary, "logo": logo}


# ---------------------------------------------------------------------------
# Prompt generation
# ---------------------------------------------------------------------------

def build_prompt_from_brief(brief, url):
    """Turn an extracted brief into a bot prompt in the BanaoBot voice.

    Mirrors the example prompts: identity + tone, a facts section taken
    only from the site, and strict no-invention rules. When the brief is
    thin, the prompt says so and stays gracefully vague instead of
    hallucinating details.
    """
    brief = brief or {}
    name = (brief.get("name") or "this business").strip()
    tagline = (brief.get("tagline") or "").strip()
    description = (brief.get("description") or "").strip()
    offerings = brief.get("offerings") or []
    prices = brief.get("prices") or []
    hours = brief.get("hours") or []
    contact = brief.get("contact") or []
    tone = (brief.get("tone") or "").strip()

    thin = not (offerings or prices or hours or contact or description)

    identity = "You are the friendly front-desk host of %s" % name
    if tagline:
        identity += " — %s" % tagline.rstrip(".")
    identity += (". You greet every visitor like a regular: warm, quick, "
                 "and a little playful.")
    if tone and "No readable text" not in tone:
        identity += " The business's own site reads as: %s" % tone

    facts = []
    if description:
        facts.append("ABOUT:\n%s" % description)
    if offerings:
        facts.append("OFFERINGS:\n" + "\n".join("- " + o for o in offerings))
    if prices:
        facts.append("PRICES SEEN ON THE SITE:\n" +
                     "\n".join("- " + p for p in prices))
    if hours:
        facts.append("HOURS:\n" + "\n".join("- " + h for h in hours))
    if contact:
        facts.append("CONTACT:\n" + "\n".join("- " + c for c in contact))
    facts_block = ("\n\n".join(facts) if facts
                   else "(The website didn't share readable details.)")

    prompt = (
        "%s\n\n"
        "WHAT YOU KNOW (everything below was read from their website, %s "
        "— it is your whole world):\n\n"
        "%s\n\n"
        "RULES:\n"
        "1. Answer questions about the business above only. If someone asks "
        "about something else, politely steer back: \"I can help with %s — "
        "what would you like to know?\"\n"
        "2. Never invent offerings, prices, hours, or contact details. If it "
        "isn't in the facts above, say so honestly: \"I don't have that "
        "info yet — the team can confirm.\"\n"
        "3. Never make up discounts, offers, or deals.\n"
        "4. Keep replies short — two or three sentences — unless someone "
        "asks for a list.\n"
        "5. If the visitor wants to buy, book, or talk to a human, take "
        "their name and number conversationally and say the team will "
        "reach out."
        % (identity, url, facts_block, name))

    if thin:
        prompt += (
            "\n\n"
            "HONESTY NOTE: The website didn't share much detail, so your "
            "facts are thin. Be upfront about that — never fill the gaps "
            "with invented specifics. Say \"I don't have that on hand yet\" "
            "and offer to pass the question to the owner, who can add more "
            "info to your prompt anytime.")

    return prompt
