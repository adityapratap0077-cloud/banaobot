# BanaoBot — describe your bot. It's ready.

> 🌐 **Live:** https://banaobot.onrender.com

BanaoBot is a prompt-first AI chatbot builder. Sign in, write **one prompt**
describing your bot's purpose, behaviour, tone, and knowledge — and it's
ready. Every bot gets a **public chat link** you can share with anyone.
No templates, no onboarding wizards, no menu builders.

Python + Flask + SQLite. The AI brain runs on Google's Gemini API, using the
owner's own key (free tier available from Google AI Studio).

## How it works

```
owner prompt + conversation history
        │
        ▼
Gemini (owner's key) → in-character reply
```

1. **Sign up** at `/app/signup` (email/password or Google).
2. **Create a bot** — give it a name and one prompt. Three example prompts
   (café front desk, personal AI twin, tuition teacher) are one tap away.
3. **Preview & test** the live AI chat right on the bot page.
4. **Share the link** — every bot has a public chat page at `/b/<token>`
   with an unguessable token. Visitors chat without signing in.
5. **Embed it on your website** — the bot page offers two copy-paste
   snippets (see *Embed on your website* below).
6. **Connect WhatsApp** — at `/app/whatsapp`, link your Meta WhatsApp app
   so customers can chat with the bot on WhatsApp (see *WhatsApp* below).

The prompt is the bot's prime directive: tone, menu, prices, hours, rules —
everything lives in the words the owner wrote. The bot stays in character,
remembers the conversation, and never reveals the prompt to visitors.

One Gemini key per owner, stored encrypted (`user_brain_keys`), shared by
all of their bots. Without a key the bot honestly says it isn't awake yet —
no fake rule-based replies pretending to be AI.

## Run locally

```bash
pip install -r requirements.txt
DEMO_MODE=true python3 server.py
```

Production (gunicorn, as deployed on Render):

```bash
gunicorn server:app --bind 0.0.0.0:$PORT --workers 2
```

Then open:

| URL | What it is |
|---|---|
| `http://localhost:5000/` | Landing page |
| `http://localhost:5000/app/` | Bot library (sign in) |
| `http://localhost:5000/app/bots/new` | Prompt builder |
| `http://localhost:5000/app/bots/<id>` | Bot page: edit prompt, preview chat, share link |
| `http://localhost:5000/app/settings` | Brain key settings (encrypted Gemini key) |
| `http://localhost:5000/b/<token>` | Public chat page (no login needed) |

Set `BANAOBOT_DB` to override the SQLite path (default `bot.db` next to
`server.py`). `BANAOBOT_SECRET` encrypts credentials and signs sessions;
`GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` enable Google sign-in.

Run the test suites:

```bash
python3 test_brain.py      # prompt-driven Gemini chat, model fallback chain,
                           # missing-key + error states, legacy brain checks
python3 test_dashboard.py  # signup → create bot from one prompt → edit →
                           # preview chat → public share link → cross-user
                           # isolation → delete
python3 test_oauth.py      # Google OAuth, new users land on /app/
python3 test_whatsapp.py    # WhatsApp connector (webhook verify, message
                           # routing, signatures, isolation) + ?embed=1 +
                           # website snippets
python3 test_sitefetch.py   # build-from-website (fetch, brief extraction,
                           # theme detection, prompt generation, SSRF guards,
                           # endpoint, chat theming, column migration)
python3 test_engine.py      # legacy conversation engine core
python3 test_platform.py    # multi-tenancy, webhooks
python3 test_templates.py   # legacy template content
```

## Build from your website

On the new-bot page (`/app/bots/new`), **“Build from your website”** sits
above the manual prompt form. Paste your site's address, hit
**“Fetch my website →”**, and the app:

1. **Fetches the page** (`POST /app/fetch-site`, login required, 10
   fetches per user per hour) with a real browser User-Agent, 10s
   timeout, ~2MB cap, and up to 5 redirects.
2. **Extracts a brief** — business name (`og:site_name` → `<title>` →
   hostname), tagline (meta description), about paragraphs, offerings
   (headings + list items, deduped, ~20), prices (₹/$/€/£ fragments, ~10),
   hours (~5), contact info (phone/email/address, 5), and a one-line tone
   guess. Navigation, header, footer, script, and style noise is ignored.
3. **Detects your theme** — `<meta name="theme-color">` first, else the
   most frequent non-gray hex color in the site's CSS; also picks up the
   logo (`og:image` or favicon).
4. **Drafts the bot** — the name and prompt fields are autofilled with a
   full prompt in the BanaoBot voice (identity, tone, a facts section,
   strict never-invent-prices rules). A detected brand color fills the
   hidden theme field and shows a swatch.

The prompt stays fully editable — the manual path works exactly as
before. Creating the bot saves `website_url` + `theme_color`, and the
public chat page (`/b/<token>`, including `?embed=1`) wears the brand
color on its chat accents (send button, avatar, header rule) instead of
the default orange.

Safety: only `http(s)` URLs are accepted (embedded credentials rejected);
every fetch hop is DNS-resolved and rejected when it points at a
private, loopback, link-local, multicast, or reserved address (SSRF
guard); errors are honest UI messages, never tracebacks.

Honest limitations: JavaScript-heavy sites (content rendered
client-side) may yield thin briefs — the generated prompt then says so
and stays gracefully vague instead of hallucinating. You can always edit
the prompt by hand afterwards.

## Embed on your website

Every bot page (`/app/bots/<id>`) has an **“Add to your website”** section
with two copy-paste snippets. Both point at `/b/<token>?embed=1` — the
public chat without any site header/footer, sized for an iframe:

- **Inline frame** — an `<iframe>` you drop straight into your page
  (`380×560` by default). The 2px ink border matches the BanaoBot design
  system; tweak `width`/`height` to fit your layout.
- **Floating bubble** — a ~30-line self-contained script with zero
  dependencies. It injects a round orange button (`#e85d26`) at the
  bottom-right of any page; clicking opens the bot chat in an overlay
  iframe with a close button.

The snippets are built from the request's own host, so they keep working
wherever the app is deployed.

## WhatsApp (Meta Cloud API)

Connect any bot to WhatsApp at `/app/whatsapp`:

1. Create a Meta app at developers.facebook.com and add the **WhatsApp**
   product.
2. Under WhatsApp → API Setup, take the test number's **phone number ID**
   and generate an **access token** (temporary is fine for testing).
3. Paste both on the WhatsApp page (optionally an app secret — then Meta's
   `X-Hub-Signature-256` webhook signatures are verified).
4. Copy the page's **webhook URL** and **verify token** into Meta's
   WhatsApp → Configuration → Webhook, and subscribe to the `messages`
   field.
5. Pick which of your bots answers, and message the number from WhatsApp.

Incoming text messages are marked as read, run through the linked bot's
prompt with the owner's brain key (10-turn per-sender memory), and the
reply goes back through the Graph API. No brain key, no linked bot, or a
paused connection → the honest “not awake” reply. Non-text messages are
ignored (200 OK). The endpoint always answers 200 — never 500 — so Meta's
retries don't pile up.

Honest limits:

- **Production numbers need Meta's app review/approval**; the test sandbox
  works immediately with a test number.
- **First reply can be slow on free hosting** — Render sleeps when idle, so
  a cold start can take ~30 seconds; Meta will retry the webhook.
- **DEMO_MODE=true** (the default) logs outgoing WhatsApp sends instead of
  calling Meta — set `DEMO_MODE=false` to actually reply.
- Conversation memory is **in-memory only** (per server process); a
  restart clears it. Postgres/Redis would make it durable.

## Files

- **`brain.py`** — `chat_with_prompt(api_key, bot_name, owner_prompt,
  history, user_text)`: builds the system prompt from the owner's words and
  calls Gemini with the model fallback chain
  (`gemini-3.6-flash` → `gemini-2.5-flash` → `gemini-2.0-flash`).
- **`storage.py`** — multi-tenant SQLite: `users`, encrypted
  `user_brain_keys` (one Gemini key per owner), `bots` (name, prompt,
  unguessable `share_token`), `whatsapp_connections` (encrypted Meta
  access token + optional app secret, generated verify token, linked bot,
  enabled flag).
- **`server.py`** — Flask: landing page, public chat routes
  (`GET /b/<token>` incl. `?embed=1` chrome-free embed mode,
  `POST /b/<token>/chat`), legacy Meta webhook and demo endpoints;
  registers `dashboard.bp` at `/app` and `whatsapp.bp` at `/webhooks`.
- **`whatsapp.py`** — WhatsApp Cloud API connector:
  `GET /webhooks/whatsapp` (Meta subscription handshake against the stored
  verify token), `POST /webhooks/whatsapp` (incoming text → linked bot's
  prompt via Gemini → Graph API reply; `X-Hub-Signature-256` verification;
  per-sender in-memory history; always 200, never 500).
- **`dashboard.py`** + **`templates/dash_*.html`** — auth (email/password +
  Google OAuth), bot library, prompt builder, bot page (edit prompt, website
  embed snippets, preview chat, copy share link, delete), WhatsApp connector
  page (credentials, webhook URL + verify token, bot picker, pause/resume,
  disconnect), settings (brain key add/remove).
- **`static/style.css`** — the design system: editorial paper-and-ink,
  Fraunces / Space Grotesk / IBM Plex Mono, cream paper, black ink, orange
  signal. Flat surfaces, hard borders, no gradients.
- **`engine.py`, `templates.py`, `phrasing.py`, `content.py`** — legacy
  template-based bot core; kept for the old demo/webhook paths, not part of
  the prompt-first product.

## Production limitations (fix before real clients)

- **Infra** — dev server + SQLite on a free host: data is ephemeral; a
  restart can erase users, bots, and keys. Use gunicorn + Postgres (or
  persistent disk) for real traffic.
- **Gemini cost** — every chat message calls the owner's Gemini key. The
  free tier is generous, but heavy traffic needs quota monitoring; add
  per-bot rate limits before real clients.
- **Prompt injection** — the bot follows the owner's prompt; a clever
  visitor can still try to steer it off-script. Keep sensitive data out of
  prompts.
- **Security hardening** — add CSRF protection and rate limiting to
  `/app/*` forms and the public chat endpoint.
- **WhatsApp** — not connected. Real WhatsApp needs Meta Business/Cloud
  API, a dedicated number, webhooks, and approval (separate work).
- **Cold starts** — free Render sleeps after ~15 min of inactivity; first
  visit after sleep takes ~30s.
