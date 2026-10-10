# WhatsApp Sales Agent

AI-powered WhatsApp sales automation built with Python, FastAPI, LangGraph, PostgreSQL and the Meta WhatsApp Cloud
API. The agent understands customer requests, searches real product data, checks stock, quotes exact prices, keeps
conversation history, creates leads and escalates to a human. **The LLM interprets and communicates; the database is
the source of truth** for products, prices and stock. See `CLAUDE.md` for the architecture rules and roadmap.

> Status: **Version 0.1**, live on a Meta Business WhatsApp number.

## Features (v0.1)

- WhatsApp in/out via Meta Cloud API (webhook verification, signature check, duplicate-event protection)
- Product search, details, price and stock lookup through typed tools (the LLM never writes SQL)
- Customer identification by phone number; persistent conversations and messages
- Lead creation on order intent; human escalation (refund, anger, explicit request, orders) with CLI hand-off
- Grounding rules: never invents products, prices or stock; never claims an order or payment happened
- Prompt-injection resistance; internal errors never reach customers
- Operator tooling: inventory import (CSV/XLSX), preflight checker, webhook simulator, real-LLM evaluation runner

## Architecture

```text
Customer -> WhatsApp -> Meta Cloud API -> POST /webhook (verify, validate, ack 200)
   -> background task: dedupe -> customer -> conversation -> LangGraph sales agent
        -> tools (products, customers, escalation) -> services -> repositories -> PostgreSQL
   -> reply via WhatsApp client (timeouts, bounded retries) -> Customer
```

| Layer | Path |
|---|---|
| API + dependencies | `app/main.py`, `app/dependencies.py` |
| Agent + prompt | `app/agents/` |
| LangGraph workflow | `app/graph/` |
| Tools (what the LLM may do) | `app/tools/` |
| Business logic | `app/services/` |
| Database models + repositories | `app/database/` |
| WhatsApp integration | `app/whatsapp/` (parser, client, webhook, settings) |
| Operator scripts | `scripts/` |

## Setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env          # fill in the variables below
python -m scripts.create_tables
python -m scripts.seed_database  # sample products
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Environment variables

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Use `postgresql+psycopg2://user:pass@host:5432/db` (SQLAlchemy 2.1 reads plain `postgresql://` as psycopg v3) |
| `GROQ_API_KEY`, `GROQ_MODEL` | LLM provider |
| `WHATSAPP_ACCESS_TOKEN` | Meta System User token (temporary dashboard tokens expire in ~24 h) |
| `WHATSAPP_PHONE_NUMBER_ID` | Numeric phone number id (not the phone number) |
| `WHATSAPP_VERIFY_TOKEN` | Any string; must match the Meta webhook config |
| `WHATSAPP_APP_SECRET` | Enables `X-Hub-Signature-256` verification. Required outside local dev |
| `APP_ENV`, `LOG_LEVEL`, `CURRENCY` | Runtime options |

Never commit `.env`.

## API

- `GET /health`
- `POST /chat` `{phone, message}` -> `{response}`: local testing without WhatsApp (disable or protect in production)
- `GET /webhook`: Meta verification handshake
- `POST /webhook`: inbound events; returns 200 fast, processes in a background task

## WhatsApp setup

Follow `docs/PHASE_9B_LIVE_TEST.md` (preflight, ngrok, Meta configuration, simulator, troubleshooting).

## Operator scripts

| Command | Purpose |
|---|---|
| `python -m scripts.create_tables` | Create all tables |
| `python -m scripts.seed_database` | Load sample products |
| `python -m scripts.import_inventory file.csv [--apply]` | Preview / apply catalogue import (CSV or XLSX) |
| `python -m scripts.check_whatsapp_setup [--webhook-url URL]` | Preflight: config, DB, Meta token, handshake |
| `python -m scripts.simulate_whatsapp_webhook --from +92...` | Send a signed fake inbound message |
| `python -m scripts.eval_conversations` | Run the CLAUDE.md §33/§34 conversations on the real model |
| `python -m scripts.escalations list\|reply\|resolve` | Human hand-off for escalated chats |

## Testing

```powershell
pytest
```

Unit and integration tests use in-memory SQLite and a scripted fake LLM: they verify wiring, grounding data flow,
persistence and failure handling. Model judgement is checked separately with `scripts.eval_conversations`
(needs a real Groq key).

## Example conversation

```text
Customer: Do you have the Logitech K380?
Agent:    Yes! The Logitech K380 Wireless Keyboard is $35, with 12 units in stock. Would you like to order one?
Customer: I need 20.
Agent:    We currently have 12 units available. Would you like 12?
Customer: I want a refund for my last order.
Agent:    I understand. I'll connect you with a member of our team who can help you further.
```

## Known limitations

- Orders and payments do not exist yet (v0.4): order intent creates a lead and escalates.
- Escalation hand-off is a CLI; there is no inbox UI or automatic staff notification yet.
- Rate limiting is in-memory per process; duplicate protection is at-most-once.
- Two rapid first messages from one new customer can open two conversations.
- No Alembic migrations yet (v0.9); `create_all` never alters existing tables.
- Free-form replies only work within 24 h of the customer's last message (Meta policy).

## Roadmap

v0.2 Sales + Support (FAQ, returns, shipping) -> v0.3 CRM -> v0.4 Orders -> v0.5 Inventory -> v0.6 MCP ->
v0.7 Multi-agent -> v0.8 Automation -> v0.9 Security/production -> v1.0 AI Business Operations Agent.
Details in `CLAUDE.md` section 5.

<!-- TODO (CLAUDE.md §65): add screenshots of a real WhatsApp conversation. -->
