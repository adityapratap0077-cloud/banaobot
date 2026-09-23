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
python3 test_engine.py      # legacy conversation engine core
python3 test_platform.py    # multi-tenancy, webhooks
python3 test_templates.py   # legacy template content
```

## Files

- **`brain.py`** — `chat_with_prompt(api_key, bot_name, owner_prompt,
  history, user_text)`: builds the system prompt from the owner's words and
  calls Gemini with the model fallback chain
  (`gemini-3.6-flash` → `gemini-2.5-flash` → `gemini-2.0-flash`).
- **`storage.py`** — multi-tenant SQLite: `users`, encrypted
  `user_brain_keys` (one Gemini key per owner), `bots` (name, prompt,
  unguessable `share_token`).
- **`server.py`** — Flask: landing page, public chat routes
  (`GET /b/<token>`, `POST /b/<token>/chat`), legacy Meta webhook and demo
  endpoints; registers `dashboard.bp` at `/app`.
- **`dashboard.py`** + **`templates/dash_*.html`** — auth (email/password +
  Google OAuth), bot library, prompt builder, bot page (edit prompt, preview
  chat, copy share link, delete), settings (brain key add/remove).
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
