# BanaoBot — make a WhatsApp bot for *your* business (free access)

> 🌐 **Live demo:** https://banaobot.onrender.com
> — chat with the demo bots instantly (no login), or open `/app/` to build your own.

BanaoBot lets **anyone** — restaurant, shop, freelancer, clinic, teacher,
creator, student, anyone — sign up, build their own WhatsApp chatbot, preview
it, and connect it to WhatsApp. No code, no Meta setup required to try it.

Rule-based engine: no LLM, no AI API, **zero per-message AI cost**.
Every bot sounds human — short WhatsApp messages, contractions, natural
Hinglish — never robotic, never "I am a bot". Python + Flask + SQLite.

A demo business is seeded — **Bhoj House** (fictional restaurant) — so the
bot core can be tested instantly without signing up. A second showcase bot
is also seeded — **Aditya Pratap** (creator/personal template): chat with it
via `POST /demo/message` with `"business_id": 2`.

## The six bot types

Pick one at signup and everything adapts — welcome copy, buttons, catalog
nouns, booking words, FAQs, tone, and even the booking flow itself:

| Bot type | Catalog | Action | Books date/time? | Default tone |
|---|---|---|---|---|
| 🍽️ Restaurant | Menu | 📅 Book a Table | ✅ (guests) | Friendly |
| 🛍️ Shop | Products | 🛒 Enquire to Order | ❌ → order enquiry → owner alert | Friendly |
| 💼 Freelancer / Services | Services | 📅 Book a Call | ✅ (people) | Professional |
| 🏥 Clinic | Treatments | 📅 Book Appointment | ✅ (patients) | Professional |
| 🎓 Teacher / Coaching | Courses | 🎓 Book Free Demo | ✅ (students) | Friendly |
| ✨ Creator / Personal | Offerings | 📅 Book a Call | ✅ (attendees) | Casual |

Details owners can change anytime in **Settings**: tone (Friendly /
Professional / Casual), catalog & action button labels (≤ 20 chars, EN + HI),
booking unit word, and whether the date/time booking flow is on.

**What each business gets**
- 👋 Welcome menu with tappable buttons (catalog / action / info)
- 🗂 Catalog browsing: categories → items with ₹ prices (veg marks for restaurants)
- 📅 Booking: date → time → unit → name → phone → confirm/cancel, with
  validation and a per-business booking ID saved to SQLite
- 🛒 Order enquiry (shops): items → name → phone → **owner alert** (no booking)
- ❓ FAQ answering in English **and** Hindi (keyword-matched, owner-editable,
  pre-seeded per template)
- 🙋 Human handoff: flags an owner alert in the dashboard
- 🗣 Human voice: greetings, fallbacks, prompts, confirmations and handoffs
  all rotate 2–4 natural variants; the bot learns and reuses the customer's
  name; per-tone phrasing packs (Friendly / Professional / Casual, EN + HI)
- 🌐 Bilingual: auto-detects Hindi (Devanagari or romanized), `/english` /
  `/hindi` to switch
- 🔌 WhatsApp connection: Meta Embedded Signup stub, one-click demo
  simulation, or manual credential paste — per business, own credentials

## Run locally (demo mode — payment-free, as requested)

```bash
cd ~/workspace/whatsapp-bot
pip install -r requirements.txt
DEMO_MODE=true python3 server.py
```

Production (gunicorn, as deployed on Render):

```bash
gunicorn server:app --bind 0.0.0.0:$PORT --workers 2
```

The repo ships a `render.yaml` blueprint — connecting the repo to Render
auto-creates the free web service with `DEMO_MODE=true` and a generated
`BANAOBOT_SECRET`.

Then open:

| URL | What it is |
|---|---|
| `http://localhost:5000/app/` | **BanaoBot dashboard** — signup, template picker, onboarding wizard, catalog builder, FAQ editor, settings, live preview, WhatsApp connect |
| `http://localhost:5000/` | Demo chat for the seeded Bhoj House bot (no login needed) |
| `http://localhost:5000/admin/bookings` | Legacy admin bookings table (demo business) |

Demo mode never touches Meta: outgoing WhatsApp messages are printed to the
console instead of sent. The preview chat posts `{phone, text, business_id}`
to `POST /demo/message`. Set `BANAOBOT_DB` to override the SQLite path
(default `bot.db` next to `server.py`).

Run the test suites:

```bash
python3 test_engine.py     # 44 scripted conversation checks (original bot core)
python3 test_platform.py   # 35 multi-tenancy checks: menu/FAQ/booking/session
                           # isolation, webhook routing by phone_number_id
python3 test_dashboard.py  # 48 HTTP checks: signup → onboarding → preview →
                           # simulated connect, cross-user isolation
python3 test_templates.py  # ~1680 checks: all six templates (labels, catalog
                           # nouns, booking units, shop enquiry flow), tone
                           # packs, and the human-voice quality bar —
                           # no bot/AI self-references, no robotic phrasing,
                           # rotating variants, name reuse, natural Hinglish
python3 e2e_teacher_shop.py # 59 end-to-end HTTP checks: real signup →
                           # onboarding → catalog API → /demo/message chats
                           # for a teacher and a shop (uses a temp DB)
```

## Aditya's self-test journey — two different bots (no clients needed)

**Bot 1 — Adiroxx Guitar Classes (teacher)**
1. Open `http://localhost:5000/app/` → **Sign up** with any email/password.
2. **Step 0 — What best describes you?** → pick 🎓 **Teacher / Coaching**.
3. Basics → name it *Adiroxx Guitar Classes*, owner phone, tagline.
4. **Build your courses** → add a category (e.g. *Guitar Courses* 🎸) and
   items with prices (e.g. *Beginner Guitar* ₹499).
5. Details → hours/address. FAQs come pre-seeded (free demo, fees…).
6. Welcome → accept the default → **Finish**.
7. Open **Preview** — the phone UI chats with *your* teacher bot:
   try `hi`, tap **🎓 View Courses**, tap **🎓 Book Free Demo** → notice it
   asks for **students**, not guests. Run `human` to see the handoff alert.

**Bot 2 — a shop**
1. Dashboard home → **+ New business** → pick 🛍️ **Shop**.
2. Name it anything, add products under **Products**.
3. Preview → tap **🛒 Enquire to Order** → type items → name → phone →
   confirm. Notice: **no date/time questions** — the enquiry lands as an
   **owner alert** on the business home page, not a booking.

Then: **Settings** → change the tone (Friendly/Professional/Casual),
rename the buttons, or switch booking on/off — preview again and hear the
voice change. Each business is fully isolated: bookings, alerts, FAQs and
sessions never leak across tenants.

## How it works

```
customer ──WhatsApp──▶ Meta ──webhook POST──▶ server.py ──▶ engine.py ──▶ replies
                              (routes by        │    ▲              │
                          phone_number_id)      │    │              ▼
                                           storage.py        Meta Cloud API
                                           (SQLite,          (per-business
                                            multi-tenant)     credentials)
```

- **`templates.py`** — the six template definitions: catalog/action nouns,
  button labels, booking units, welcome copy, FAQ seeds, default tone,
  booking confirmations. Pure data + render helpers; the single source of
  truth for template copy.
- **`phrasing.py`** — the human-voice layer: Friendly / Professional / Casual
  packs in English + Hinglish, 2–4 rotating variants per line, `{name}`
  placeholders. The test suite scans every generated reply for bot/AI
  self-references and robotic phrasing.
- **`engine.py`** — pure conversation logic.
  `handle_message(phone, text, session, business)` returns
  `(replies, new_session)` in WhatsApp Cloud API format (text / interactive
  buttons / interactive lists). Reads **only the supplied business bundle**
  (template + settings + catalog + FAQs); `business=None` falls back to the
  Bhoj House content (backward compatible). Side effects come back as
  `new_session["_events"]` (`save_booking`, `owner_alert`) — the engine
  itself does no I/O. Booking on/off resolves from the business setting
  (`_booking_on`), so a shop never enters the date/time flow.
- **`storage.py`** — multi-tenant SQLite: `users`, **`templates`** (seeded
  from the registry — the queryable record of available bot types),
  `businesses` (with `template_id`, editable label overrides, `tone`,
  `booking_enabled`), `menu_categories`, `menu_items`, per-business `faqs`;
  business-scoped `sessions`, `bookings`, `owner_alerts`, `message_log`.
  Per-business WhatsApp credentials stored encrypted (Fernet when
  `cryptography` is installed, XOR fallback otherwise — see production
  notes). Bhoj House seeded from `content.py`.
- **`server.py`** — Flask: Meta webhook verify/receive (routes by
  `phone_number_id` → business), demo simulator endpoints, per-business
  Cloud API sender, legacy admin pages. Registers `dashboard.bp` at `/app`.
- **`dashboard.py`** + **`templates/dash_*.html`** — self-serve web app:
  auth (werkzeug password hashing, sessions), 6-step onboarding wizard
  (template picker → basics → catalog → details → FAQs → welcome), catalog
  builder (+ JSON API with validation), FAQ editor, settings (tone, labels,
  booking toggle), live preview (WhatsApp-style phone UI), connect page
  (Embedded Signup stub, demo simulation, manual credentials), Meta go-live
  checklist. All business routes are ownership-checked
  (`own_business_or_404` — a second user gets 404, never data).
- **`demo.html`** — original phone-style chat UI (Bhoj House demo).

## Honest limitation: what templates can and can't do

Templates configure the **known flows** — catalog browsing, date/time
booking, order enquiry, FAQs, handoff, bilingual greetings. If a business
needs an **arbitrary custom workflow** (e.g. a loan-application form with
conditional branches, a multi-step quiz with scoring), that needs a visual
flow builder or custom state-machine code: new session states, validation,
storage/actions and tests. Templates get you from zero to a working,
human-sounding bot for the six covered archetypes; they are not a
general-purpose chatbot authoring language.

## Going live for a real client (per business)

1. **Meta Business Manager** — business.facebook.com (free); verify the
   business (documents; takes a few days).
2. **Phone number** — a dedicated SIM/number that has *never* been on
   WhatsApp; add it to the WhatsApp Business Account.
3. **Meta App** — developers.facebook.com → create app → add *WhatsApp*
   product → connect the WhatsApp Business Account.
4. **Webhook** — deploy this server with HTTPS. The repo includes
   `render.yaml`: connect the repo in Render's dashboard and it provisions a
   free web service automatically (or deploy on Railway/VPS with gunicorn).
   In the app dashboard set:
   - Callback URL: `https://YOUR-DOMAIN/webhook`
   - Verify token: your `VERIFY_TOKEN` env var (no default — set one)
   - Subscribe to the `messages` webhook field.
5. **Token** — create a permanent *system user* access token with
   `whatsapp_business_messaging` permission; note the *phone number ID*.
6. In the dashboard's **Connect WhatsApp** page for that business: paste the
   phone number ID + token (or use the Embedded Signup once `META_APP_ID`
   is configured) → status `connected`.
7. Run with `DEMO_MODE=false`; the webhook routes each incoming message to
   the right business by its `phone_number_id` automatically.
8. **Message templates** — for proactive messages (order updates, promos),
   create and get Meta approval for templates. Replies inside the 24-hour
   customer-service window need no template.

## Billing plug-in point (Razorpay later — not in this version)

Access is currently **free**. The intended future model: free trial →
paid subscription via Razorpay. Plug-in points are ready:

- `businesses.status` already has `draft` / `active` / `connected` states —
  add `suspended`/`trial_expired` here and gate the webhook + preview on it.
- `users` table owns each business — attach a Razorpay customer +
  subscription id to the user row.
- Natural enforcement points: `server.process_message()` (drop/queue
  messages for unpaid businesses), `dashboard` preview page, and the
  connect page.
- Suggested flow later: Razorpay subscription (`plan_id` per tier) → webhook
  signature verification → flip `status` → monthly invoice via Razorpay.

## Cost breakdown (India, per client)

| Item | Cost |
|---|---|
| BanaoBot software | ₹0 — you own it |
| Server (demo) | ₹0 (Render/Railway free tier) |
| Server (production) | ~₹500/mo VPS — hosts *many* businesses at once |
| Client's SIM | ~₹200 one-time (client pays) |
| Meta per-message | ~₹0.86 marketing · ~₹0.12 utility · free in 24h window (client pays Meta directly; a local shop ≈ ₹100–300/mo) |
| Razorpay (later) | ~2% + GST per transaction (only when you charge) |
| AI API | ₹0 — rule-based, no LLM |

Suggested pricing to a client later: **₹5,000–15,000 setup +
₹1,000–2,000/mo maintenance.**

## Production limitations (fix before real clients)

- **Credential encryption** — without the `cryptography` package, stored
  WhatsApp tokens use a XOR/base64 fallback (obfuscation, not real
  encryption). Install `cryptography` (Fernet path activates automatically)
  and set a strong `BANAOBOT_SECRET`, or use a secrets manager/KMS.
- **App review** — Meta requires review for `whatsapp_business_management`
  and `whatsapp_business_messaging` before other businesses can connect.
- **Message templates** — engine sends free-form replies only; add a
  `send_template` path for proactive outreach.
- **Infra** — dev server + SQLite: use gunicorn + Postgres for real traffic.
- **Security hardening** — add CSRF protection and rate limiting to
  `/app/*` forms and the JSON API.
- **`/connect/exchange`** — production must exchange the Meta `code` for a
  real system-user token via the Graph API (marked `PRODUCTION:` in code).
- **Deployment** — no public tunnel is bundled; deploy to a host with HTTPS
  for the Meta webhook (Render/Railway/VPS).
