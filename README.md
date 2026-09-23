<div align="center">

# BANAOBOT
### Describe your bot. It's ready. — Prompt-first AI chatbot builder

![BanaoBot](https://img.shields.io/badge/BANAOBOT-2026-%23F2F0EB?style=for-the-badge&labelColor=%23060608)
![Live](https://img.shields.io/badge/LIVE-banaobot.onrender.com-%237A1212?style=for-the-badge&labelColor=%23060608)
![License](https://img.shields.io/badge/License-MIT-%23060608?style=for-the-badge)

**Sign up. Write one prompt. Share the link.**

[Launch BanaoBot](https://banaobot.onrender.com) • [GitHub](https://github.com/adityapratap0077-cloud)

</div>

---

BanaoBot is a prompt-first AI chatbot builder. Sign in, write **one prompt** describing your bot's purpose, behaviour, tone, and knowledge — and it's ready. Every bot gets a **public chat link** you can share with anyone. No templates, no onboarding wizards, no menu builders.

Python + Flask + PostgreSQL (Render) / SQLite (local). The AI brain runs on **Google's Gemini API using your own key** (free tier from Google AI Studio) — one encrypted key per owner, shared by all your bots.

## How it works

```
owner prompt + conversation history
        │
        ▼
Gemini (owner's key) → in-character reply
```

1. **Sign up** at `/app/signup` (email/password or Google).
2. **Add your Gemini key** in Settings — without a key the bot honestly says it isn't awake yet; no fake rule-based replies pretending to be AI.
3. **Create a bot** — give it a name and one prompt. Example prompts (café front desk, personal AI twin, tuition teacher) are one tap away.
4. **Preview & test** the live AI chat right on the bot page, with owner-only diagnostics when something fails (bad key, quota, network — visitors never see these).
5. **Share the link** — every bot has a public chat page at `/b/<token>` with an unguessable token. Visitors chat without signing in.
6. **Embed it on your website** — every bot page offers two copy-paste snippets: an inline iframe (`/b/<token>?embed=1`) and a floating bubble script with zero dependencies.

The prompt is the bot's prime directive: tone, menu, prices, hours, rules — everything lives in the words you wrote. The bot stays in character, remembers the conversation, and never reveals the prompt to visitors.

## Features

- **One-prompt bot creation** — purpose, behaviour, tone, knowledge in plain words
- **Your Gemini key** — stored encrypted, shared across your bots; model fallback chain (`gemini-3.6-flash` → `2.5-flash` → `2.0-flash`)
- **Public share links** — `/b/<token>`, unguessable, no login needed for visitors
- **Website embeds** — inline iframe + floating bubble, themed to your brand color
- **Build from your website** — paste a site URL; the app fetches it, extracts a brief (name, offerings, prices, hours, theme color) and drafts your bot's prompt. SSRF-guarded, honest when a site is too JS-heavy to read
- **Menu-to-catalogue helper** — `menu_import.py` parses pasted menu text or a menu photo/PDF (free OCR.space tier) into structured items with categories and prices, tuned for Indian menus in English, Hindi (Devanagari), and Hinglish. It ships as a tested helper module, not yet wired into the dashboard UI
- **WhatsApp connector** — full Meta Cloud API wiring (`/app/whatsapp`, webhook verification, signature checks, per-sender memory). See Honest limitations below

## WhatsApp — demo/simulation mode by default

The WhatsApp integration is fully built: link your Meta WhatsApp app at `/app/whatsapp`, and incoming messages run through your bot's prompt with your Gemini key. But it is **not live WhatsApp delivery**:

- **Demo mode is the default** — `DEMO_MODE=true` (how production is deployed) *logs outgoing WhatsApp sends instead of calling Meta*. No message actually reaches WhatsApp.
- **Real delivery** needs your own Meta app credentials (phone number ID + access token) *and* `DEMO_MODE=false` — plus Meta's app review for production numbers.
- **Cold starts** on free hosting — Render sleeps when idle; a first visit after sleep can take ~30 seconds, which is slow enough that Meta may retry the webhook.
- **In-memory conversation memory** — per-sender history clears on restart.

Until those are flipped, treat WhatsApp as a working connector in simulation mode.

## Run locally

```bash
pip install -r requirements.txt
DEMO_MODE=true python3 server.py
```

Production (gunicorn, as deployed on Render):

```bash
gunicorn server:app --bind 0.0.0.0:$PORT --workers 2
```

Set `BANAOBOT_DB` to override the SQLite path. Set `DATABASE_URL` to use PostgreSQL (Render): the app then stores users, bots, and encrypted keys in Postgres so data survives deploys and restarts — without it, everything is local SQLite, which is fine for dev only. `BANAOBOT_SECRET` encrypts credentials and signs sessions; `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` enable Google sign-in.

## Test suites

```bash
python3 test_brain.py       # prompt-driven Gemini chat, model fallback, missing-key + error states
python3 test_dashboard.py    # signup → create bot from one prompt → edit → preview → share link → isolation → delete
python3 test_oauth.py        # Google OAuth, new users land on /app/
python3 test_whatsapp.py    # WhatsApp connector: webhook verify, routing, signatures, isolation, embeds
python3 test_sitefetch.py   # build-from-website: fetch, brief extraction, theme detection, SSRF guards
python3 test_postgres_compat.py  # dual-dialect storage layer (SQLite-only, no live PG)
python3 test_engine.py       # legacy conversation engine core
python3 test_platform.py    # multi-tenancy, webhooks
python3 test_templates.py   # legacy template content
```

## Honest limitations (fix before real clients)

- **Free Postgres expires** — Render's free Postgres has an expiry date (check the Render dashboard). The long-term move is a persistent provider before real client data depends on it.
- **Gemini cost** — every chat message calls the owner's key. The free tier is generous, but heavy traffic needs quota monitoring and per-bot rate limits first.
- **Prompt injection** — the bot follows the owner's prompt, but a clever visitor can try to steer it off-script. Keep sensitive data out of prompts.
- **Security hardening** — add CSRF protection and rate limiting to `/app/*` forms and the public chat endpoint before real clients.
- **Cold starts** — free Render sleeps after ~15 min of inactivity; first visit after sleep takes ~30s.

---

## Design System

Editorial paper-and-ink — the bot that feels like a printed page.

### Color Palette

| Color | Hex | Usage |
| :--- | :--- | :--- |
| Cream Paper | `#F5F1E8` | Background |
| Black Ink | `#111111` | Text |
| Signal Orange | `#E85D26` | Accent — send button, bubble, header rule |

### Typography

- **Display:** Fraunces — editorial serif
- **Body:** Space Grotesk — clean, modern
- **Mono:** IBM Plex Mono — technical labels

Flat surfaces, hard borders, no gradients.

---

## Tech Stack

`Python / Flask / PostgreSQL / SQLite / Gemini API / gunicorn / Render`

## Deploy

Render web service: `render.yaml` included. Push to `main` and Render redeploys.

---

## Author

**Aditya Pratap** — Creative Technologist
Gorakhpur, India — github.com/adityapratap0077-cloud

## License

MIT © Aditya Pratap
